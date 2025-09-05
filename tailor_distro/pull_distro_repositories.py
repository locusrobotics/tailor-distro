#!/usr/bin/python3
import argparse
import click
import pathlib
import rosdistro
import sys
import tarfile
import glob
import shutil
import github

from requests.exceptions import HTTPError
from catkin_pkg.package import parse_package
from concurrent.futures import ThreadPoolExecutor, as_completed
from jinja2 import Environment, BaseLoader
from shutil import rmtree
from typing import Any, List, Mapping, Optional, Dict, Tuple
from urllib import request, error
from time import sleep
from textwrap import indent
import tempfile

from . import YamlLoadAction

PULL_WORKERS = 10
DOWNLOAD_RETRIES = 3
RETRY_WAIT_SECONDS = 15
DOWNLOAD_TIMEOUT_SEC = 30
CHUNK_SIZE = 1024 * 1024


def get_name_and_owner(repo_url: str) -> Tuple[Optional[str], str]:
    """
    Parse the repository url to obtain the name and owner data.
    :param repo_url: Repository URL
    :returns: Tuple {owner, repo_name}
    """
    repo_url = repo_url.rstrip("/").removesuffix(".git")
    if repo_url.startswith("http"):
        repo_url = repo_url.split("/", 3)[3]
    else:
        click.echo(
            click.style("Unexpected URL format for repo: {repo_url}", fg="yellow"),
            err=True,
        )
        return (None, None)
    parts = repo_url.split("/", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (parts[0], None)

def graphql_with_retry(requester, query, max_attempts=DOWNLOAD_RETRIES, delay=RETRY_WAIT_SECONDS):

    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return requester.graphql_query(query, {})
        except HTTPError as e:
            status = getattr(e.response, "status_code", None)
            # Don't retry on errors from which we cannot recover
            if status in (400, 401, 403):
                click.echo(click.style(f"Client error {status}, not retrying.", fg="red"), err=True)
                raise
            last_error = e
            click.echo(click.style(f"[Attempt {attempt}] HTTPError: {e}", fg="yellow"), err=True)
        except Exception as e:
            last_error = e
            click.echo(click.style(f"[Attempt {attempt}] Error: {e}", fg="yellow"), err=True)
        if attempt == max_attempts:
            click.echo(click.style("Reached maximum request attemmpts", fg="red"),err=True)
            break

        sleep(delay)

    raise last_error


def retrieve_tarballs(
    repos_url: List[str], refs: List[str], github_client, chunk: int = 100
) -> Dict[str, Dict[str, str | bool]]:
    """
    Retrieve the tarball for a list of repositories using the GraphQL API of Github. If the ref_branch exists,
    the tarball corresponding to that reference is returned. Otherwise, exists bool is set to False.
    :param repos_url: list of repository URLs
    :param refs: default versions to retrieve
    :param github_client: Github client
    :chunk: limit of the number of repositories that can be processed to avoid running into rate limit issues
    :returns: a dictionary such as d[repo_name] ={exists: True/False, sha: str, tarball: str}
    """
    names_and_owners = [get_name_and_owner(url) for url in repos_url]
    requester = github_client._Github__requester

    out: Dict[str, Dict[str, str | bool]] = {}
    for start in range(0, len(names_and_owners), chunk):
        slice_ = names_and_owners[start:start + chunk]
        slice_refs = refs[start:start + chunk]
        query_content = []
        for idx, ((repo_owner, repo_name), ref) in enumerate(zip(slice_, slice_refs)):
            alias = f"r{idx}"
            query_content.append(
                f"""
              {alias}: repository(owner: "{repo_owner}", name: "{repo_name}") {{
                version: object(expression:"{ref}") {{
                  __typename
                  ... on Commit {{ oid tarballUrl }}
                  ... on Tag {{
                    target {{ ... on Commit {{ oid tarballUrl }} oid }}
                  }}
                }}
              }}"""
            )

        query = f"query {{\n{indent(''.join(query_content), '  ')}\n}}"
        _, result = graphql_with_retry(requester, query)

        for idx, ((repo_owner, repo_name), ref) in enumerate(zip(slice_, slice_refs)):
            node = result["data"][f"r{idx}"]
            if node["version"] is not None:
                v = node["version"]
                if v["__typename"] == "Commit":
                    sha = v["oid"]
                    tarball = v["tarballUrl"]
                else:
                    sha = v["target"]["oid"]
                    tarball = v["target"]["tarballUrl"]
                click.echo(f"Obtained tarball URL for {repo_name}... (ref: {ref})")
                exists = True
            else:
                exists = False
                sha = ""
                tarball = ""
                click.echo(
                    click.style(
                        f"Could not obtain tarball URL for {repo_name}... (ref: {ref})",
                        fg="red",
                    )
                )
            out[repo_name] = {
                "exists": exists,
                "sha": sha,
                "tarball": tarball,
            }
    return out


def process_repo(repo: str, tarball_url: str, base_dir: pathlib.Path) -> None:
    """Download and unpack a single repository using its tarball URL
    :param repo: Name of the repository
    :param tarball_url: Tarball URL
    :param base_dir: Directory where to unpack the repositoriess
    """
    repo_dir = base_dir / repo
    repo_dir.mkdir(parents=True, exist_ok=True)
    retries = DOWNLOAD_RETRIES
    while True:
        try:
            tmp = tempfile.NamedTemporaryFile(delete=False, dir=repo_dir)
            with request.urlopen(tarball_url, timeout=60) as src:
                while True:
                    chunk = src.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    tmp.write(chunk)
            tmp.close()
            archive_path = repo_dir / f"{repo}.tar.gz"
            pathlib.Path(tmp.name).replace(archive_path)
            break
        except (error.HTTPError, error.URLError, OSError) as exc:
            if retries == 0:
                raise RuntimeError(f"{repo}: download failed ({exc})") from exc
            retries -= 1
            click.echo(
                click.style(
                    f"{repo}: {exc} - retrying in {RETRY_WAIT_SECONDS}s "
                    f"({retries} left)",
                    fg="yellow",
                ),
                err=True,
            )
            sleep(RETRY_WAIT_SECONDS)
    with tarfile.open(archive_path) as tar:
        tar.extractall(path=repo_dir)


def pull_repositories(
    repo_data: Dict[str, Dict[str, str | bool]], base_dir: pathlib.Path
) -> None:
    """Download and unpack a list of repository tarballs
    :param repo_data: List of repository names and their tarball URLs
    :param base_dir: Directory where to unpack the repositories
    """
    click.echo("Download and unpack repositories...", err=False)
    base_dir.mkdir(parents=True, exist_ok=True)

    # Check if the tarballUrl exists
    repo_tarballs: Dict[str, str] = {}
    for repo_name, data in repo_data.items():
        if data["exists"]:
            repo_tarballs[repo_name] = data["tarball"]

    with ThreadPoolExecutor(max_workers=PULL_WORKERS) as pool:
        futures = {
            pool.submit(process_repo, repo, url, base_dir): repo
            for repo, url in repo_tarballs.items()
        }

        for future in as_completed(futures):
            repo_name = futures[future]
            try:
                future.result()
                # click.echo(click.style(f"[✓] Downloaded {repo_name}", fg="green"), err=False)
            except Exception as exc:
                click.echo(
                    click.style(f"[✗] Could not download {repo_name}: {exc}", fg="red"),
                    err=True,
                )
                raise


def remove_packages(whitelisted_pkgs: Dict[str, List[str]]) -> None:
    """
    Remove all except whitelisted packages
    param: whitelisted_pkgs: List of whitelisted packages
    """
    for repo_dir, whitelist in whitelisted_pkgs.items():
        # skip if no whitelist (i.e. keep everything)
        if not whitelist:
            continue
        try:
            found_packages = glob.glob(str(repo_dir / "**/package.xml"), recursive=True)
            for package_xml_path in found_packages:
                package = parse_package(package_xml_path)
                if package.name not in whitelist:
                    click.echo(f"Removing {package.name}, not in whitelist", err=True)
                    shutil.rmtree(pathlib.Path(package_xml_path).parent.resolve())
        except Exception as e:
            click.echo(
                click.style(
                    f"Unable to reduce {repo_dir} to whitelist {whitelist}: {e}",
                    fg="yellow",
                ),
                err=True,
            )
            raise


def pull_distro_repositories(
    src_dir: pathlib.Path,
    recipes: Mapping[str, Any],
    rosdistro_index: pathlib.Path,
    github_key: str,
    clean: bool,
) -> int:
    """Pull all the packages in all ROS distributions to disk
    :param src_dir: Directory where sources should be pulled.
    :param recipes: Recipe configuration defining distributions.
    :param rosdistro_index: Path to rosdistro index.
    :param github_key: Github API key.
    :param clean: Whether to delete distro folders before pulling.
    :returns: Result code
    """
    index = rosdistro.get_index(rosdistro_index.resolve().as_uri())
    github_client = github.Github(github_key)
    common_options = recipes["common"]

    for distro_name, distro_options in common_options["distributions"].items():
        click.echo(
            click.style(
                f"Processing repositories for {distro_name} distro...", fg="green"
            ),
            err=False,
        )
        distro = rosdistro.get_distribution(index, distro_name)
        target_dir = src_dir / distro_name

        repo_ids = []
        refs = []
        whitelisted_pkgs: Dict[str, List[str]] = {}
        if clean and target_dir.exists():
            click.echo(f"Deleting {target_dir} ...", err=False)
            rmtree(str(target_dir))

        target_dir.mkdir(parents=True, exist_ok=not clean)
        for repo_name, distro_data in distro.repositories.items():
            # release.url overrides source.url. In most cases they should be equivalent, but sometimes we want to
            # pull from a bloomed repository with patches
            try:
                url = distro_data.release_repository.url
            except AttributeError:
                url = distro_data.source_repository.url

            # We're fitting to the rosdistro standard here, release.tags.release is a template that can take
            # parameters, though in our case it's usually just '{{ version }}'.
            if (
                distro_data.release_repository
                and distro_data.release_repository.version is not None
            ):
                version_template = distro_data.release_repository.tags["release"]
                context = {
                    "package": repo_name,
                    "upstream": distro_options["upstream"]["name"],
                    "version": distro_data.release_repository.version,
                }
                version = (
                    Environment(loader=BaseLoader())
                    .from_string(version_template)
                    .render(**context)
                )
            else:
                version = distro_data.source_repository.version

            # Repurpose the rosdistro 'release.packages' field as an optional whitelist to prevent building
            # packages we don't want.
            if (
                distro_data.release_repository
                and distro_data.release_repository.package_names != [repo_name]
            ):
                repo_dir = target_dir / repo_name
                whitelisted_pkgs[repo_dir] = (
                    distro_data.release_repository.package_names
                )

            # click.echo(click.style(f"Adding '{repo_name}'"), err=False)
            repo_ids.append(url)
            refs.append(version)

        repositories_data = retrieve_tarballs(repo_ids, refs, github_client)
        pull_repositories(repositories_data, target_dir)
        remove_packages(whitelisted_pkgs)
    return 0


def main():
    parser = argparse.ArgumentParser(description=pull_distro_repositories.__doc__)
    parser.add_argument("--src-dir", type=pathlib.Path, required=True)
    parser.add_argument("--recipes", action=YamlLoadAction, required=True)
    parser.add_argument("--rosdistro-index", type=pathlib.Path, required=True)
    parser.add_argument("--github-key", type=str)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    sys.exit(pull_distro_repositories(**vars(args)))


if __name__ == "__main__":
    main()

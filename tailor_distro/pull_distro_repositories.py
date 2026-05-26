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
import json
import os

from dataclasses import dataclass
from requests.exceptions import HTTPError
from catkin_pkg.package import parse_package
from concurrent.futures import ThreadPoolExecutor, as_completed
from jinja2 import Environment, BaseLoader
from shutil import rmtree
from typing import Any, List, Mapping, Optional, Dict, Tuple
from urllib import request, error, parse
from time import sleep
from textwrap import indent
import tempfile

from . import YamlLoadAction

PULL_WORKERS = 10
DOWNLOAD_RETRIES = 3
RETRY_WAIT_SECONDS = 15
DOWNLOAD_TIMEOUT_SEC = 30
CHUNK_SIZE = 1024 * 1024

@dataclass
class RepoInformation:
    owner: str
    name: str
    exists: bool
    sha: str
    tarball: str

def get_repository_info(repo_url: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Parse repository URL to obtain provider, owner namespace and repository name.
    :param repo_url: Repository URL
    :returns: Tuple {provider, owner, repo_name}
    """
    normalized_url = repo_url.rstrip("/").removesuffix(".git")
    parsed = parse.urlsplit(normalized_url)
    host = (parsed.hostname or "").lower()
    parts = [p for p in parsed.path.strip("/").split("/") if p]

    if parsed.scheme not in {"http", "https"} or len(parts) < 2:
        click.echo(
            click.style(f"Unexpected URL format for repo: {repo_url}", fg="yellow"),
            err=True,
        )
        return (None, None, None)

    if host in {"github.com", "www.github.com"}:
        return ("github", parts[0], parts[1])
    if host in {"gitlab.com", "www.gitlab.com"}:
        # GitLab groups can be nested; repository name is always the last segment.
        return ("gitlab", "/".join(parts[:-1]), parts[-1])

    click.echo(
        click.style(f"Unsupported repository host '{host}' for repo: {repo_url}", fg="yellow"),
        err=True,
    )
    return (None, None, None)


def gitlab_commit_with_retry(
    owner: str,
    repo_name: str,
    ref: str,
    max_attempts=DOWNLOAD_RETRIES,
    delay=RETRY_WAIT_SECONDS,
) -> Dict[str, Any]:
    """Resolve a public gitlab.com ref to a commit object."""

    project_path = parse.quote(f"{owner}/{repo_name}", safe="")
    encoded_ref = parse.quote(ref, safe="")
    url = (
        f"https://gitlab.com/api/v4/projects/{project_path}/repository/commits/{encoded_ref}"
    )

    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            with request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_SEC) as src:
                return json.load(src)
        except error.HTTPError as e:
            if e.code in (400, 401, 403, 404):
                click.echo(click.style(f"Client error {e.code}, not retrying.", fg="red"), err=True)
                raise
            last_error = e
            click.echo(click.style(f"[Attempt {attempt}] HTTPError: {e}", fg="yellow"), err=True)
        except (error.URLError, OSError, ValueError) as e:
            last_error = e
            click.echo(click.style(f"[Attempt {attempt}] Error: {e}", fg="yellow"), err=True)

        if attempt == max_attempts:
            click.echo(click.style("Reached maximum request attempts", fg="red"), err=True)
            break
        sleep(delay)

    raise last_error

def graphql_with_retry(requester, query, max_attempts=DOWNLOAD_RETRIES, delay=RETRY_WAIT_SECONDS):

    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return requester.graphql_query(query, {})
        except HTTPError as e:
            status = getattr(e.response, "status_code", None)
            # Don't retry on errors from which we cannot recover
            if status in (400, 401, 403, 404):
                click.echo(click.style(f"Client error {status}, not retrying.", fg="red"), err=True)
                raise
            last_error = e
            click.echo(click.style(f"[Attempt {attempt}] HTTPError: {e}", fg="yellow"), err=True)
        except Exception as e:
            last_error = e
            click.echo(click.style(f"[Attempt {attempt}] Error: {e}", fg="yellow"), err=True)
        if attempt == max_attempts:
            click.echo(click.style("Reached maximum request attempts", fg="red"), err=True)
            break

        sleep(delay)

    raise last_error


def retrieve_gitlab_tarball(
    repo_owner: str,
    repo_name: str,
    ref: str,
) -> RepoInformation:
    """Resolve a GitLab ref and return tarball metadata for a single repository."""

    try:
        commit_data = gitlab_commit_with_retry(repo_owner, repo_name, ref)
        sha = commit_data.get("id")
    except Exception as exc:
        click.echo(
            click.style(
                f"Failed to retrieve commit data for {repo_owner}/{repo_name} with ref '{ref}': {exc}",
                fg="yellow",
            ),
            err=True,
        )
        raise

    project_path = parse.quote(f"{repo_owner}/{repo_name}", safe="")
    encoded_sha = parse.quote(sha, safe="")
    tarball = (
        f"https://gitlab.com/api/v4/projects/{project_path}/repository/archive.tar.gz"
        f"?sha={encoded_sha}"
    )

    click.echo(f"Obtained tarball URL for {repo_name}... (ref: {ref}, sha: {sha})")
    return RepoInformation(
        owner=repo_owner,
        name=repo_name,
        exists=True,
        sha=sha,
        tarball=tarball,
    )


def retrieve_tarballs(
    repos_url: List[str], refs: List[str], github_client, chunk: int = 100
) -> List[RepoInformation]:
    """
    Retrieve the tarball for a list of repositories using the GraphQL API of Github. If the ref_branch exists,
    the tarball corresponding to that reference is returned. Otherwise, exists bool is set to False.
    :param repos_url: list of repository URLs
    :param refs: default versions to retrieve
    :param github_client: Github client
    :chunk: limit of the number of repositories that can be processed to avoid running into rate limit issues
    :returns: a list of RepoInformation objects containing all relevant data
    """
    requester = github_client._Github__requester
    entries = list(zip(repos_url, refs))
    github_entries: List[Tuple[str, str, str]] = []
    out: List[RepoInformation] = []

    for idx, (repo_url, ref) in enumerate(entries):
        provider, repo_owner, repo_name = get_repository_info(repo_url)
        if not provider or not repo_owner or not repo_name:
            raise RuntimeError(f"Could not parse provider/owner/name from repository URL: {repo_url}")

        if provider == "gitlab":
            out.append(retrieve_gitlab_tarball(repo_owner, repo_name, ref))
        elif provider == "github":
            github_entries.append((repo_owner, repo_name, ref))
        else:
            raise RuntimeError(f"Unsupported provider for {repo_url}")

    # Retrieve Github repository tarball URLs in batches
    for start in range(0, len(github_entries), chunk):
        slice_ = github_entries[start:start + chunk]
        query_content = []
        for idx, (repo_owner, repo_name, ref) in enumerate(slice_):
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

        for idx, (repo_owner, repo_name, ref) in enumerate(slice_):
            node = result["data"][f"r{idx}"]
            if node["version"] is not None:
                v = node["version"]
                if v["__typename"] == "Commit":
                    sha = v["oid"]
                    tarball = v["tarballUrl"]
                else:
                    sha = v["target"]["oid"]
                    tarball = v["target"]["tarballUrl"]
                click.echo(f"Obtained tarball URL for {repo_name}... (ref: {ref}, sha: {sha})")
                exists = True
            else:
                raise RuntimeError(
                    f"Could not obtain tarball URL for {repo_name}... (ref: {ref})"
                )
            out.append(
                RepoInformation(
                    owner=repo_owner,
                    name=repo_name,
                    exists=exists,
                    sha=sha,
                    tarball=tarball,
                )
            )
    return out


def process_repo(repo: str, tarball_url: str, target_dir: pathlib.Path) -> pathlib.Path:
    """Download and unpack a single repository using its tarball URL
    :param repo: Name of the repository
    :param tarball_url: Tarball URL
    :param target_dir: Directory where to unpack the repositoriess
    :returns: the relative path where the repository has been extracted
    """
    repo_dir = target_dir / repo
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

    # Rename the extracted dir as the repository name without any sha
    extracted_dir = None
    extracted_dir = next(
        name for name in os.listdir(repo_dir)
        if os.path.isdir(os.path.join(repo_dir, name))
    )
    if extracted_dir is not None:
        os.rename(
            os.path.join(repo_dir, extracted_dir),
            os.path.join(repo_dir, repo),
        )

    # Return the path of the extracted repository
    dirs = [p for p in repo_dir.iterdir() if p.is_dir()]
    if len(dirs) == 1:
        return dirs[0]
    return repo_dir


def append_jsonl(log_path: pathlib.Path, repo_info: RepoInformation, repo_path: pathlib.Path) -> None:
    """Append repository information to json log file
    :param log_path: path of the log file
    :param repo_info: RepoInformation object containing all relevant data
    :param repo_path: Path where the repository has been extracted to
    """

    log_path.parent.mkdir(parents=True, exist_ok=True)
    repo_log = {
        "owner": repo_info.owner,
        "repo": repo_info.name,
        "sha": repo_info.sha,
        "path": str(repo_path),
    }
    line = json.dumps(repo_log, ensure_ascii=False) + "\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line)


def pull_repositories(
    repo_data: List[RepoInformation], base_dir: pathlib.Path, distro_name: str
) -> None:
    """Download and unpack a list of repository tarballs
    :param repo_data: List of RepoInformation class
    :param base_dir: Directory where to unpack the repositories
    :param distro_name: Name of the distribution
    """
    click.echo("Download and unpack repositories...", err=False)
    base_dir.mkdir(parents=True, exist_ok=True)
    logfile_path = base_dir / f"{distro_name}_repositories_data.jsonl"

    with ThreadPoolExecutor(max_workers=PULL_WORKERS) as pool:
        futures = {
            pool.submit(process_repo, repo.name, repo.tarball, base_dir): repo
            for repo in repo_data
            if repo.exists
        }

        for future in as_completed(futures):
            repo_info = futures[future]
            try:
                repo_path = future.result()
            except Exception as exc:
                click.echo(
                    click.style(f"[✗] Could not download {repo_info.name}: {exc}", fg="red"),
                    err=True,
                )
                raise
            append_jsonl(logfile_path, repo_info, repo_path)



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
        pull_repositories(repositories_data, target_dir, distro_name)
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

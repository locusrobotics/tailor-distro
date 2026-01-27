import argparse
import apt
import apt_pkg
import jinja2
import os
import stat
import re
import yaml
import subprocess
import logging
import requests
import json

from concurrent.futures import ThreadPoolExecutor, as_completed

from collections import defaultdict
from functools import lru_cache
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import (
    List,
    Dict,
    Any,
    Tuple,
    TypeVar
)

from catkin_pkg.topological_order import topological_order
from catkin_pkg.package import Package
from rosdep2.sources_list import SourcesListLoader
from rosdep2.lookup import RosdepLookup, ResolutionError
from rosdep2.rospkg_loader import DEFAULT_VIEW_KEY

from . import debian_templates
from .recipes import load_recipes, GlobalRecipe

TEMPLATE_SUFFIX = ".j2"
SCHEME_S3 = "s3://"
APT_REGION = os.environ.get("LOCUS_APT_REGION", "us-east-1")
APT_REPO = os.environ.get("LOCUS_APT_REPO", "s3://locus-tailor-artifacts")

APT_MIRRORS: Dict[str, List[str]] = {
    "jammy": [],
    "noble": []
}


NAME_RE = re.compile(
    r"^(?P<organization>[A-Za-z0-9._-]+)-"
    r"(?P<release_label>[A-Za-z0-9._-]+)-"
    r"(?P<distribution>[A-Za-z0-9._-]+)-"
    r"(?P<name_dashed>[A-Za-z0-9._-]+)$"
)

VERSION_RE = re.compile(
    r"^(?P<version>[A-Za-z0-9._~+-]+)-"
    r"(?P<build_date>\d{8,14})"
    r"\+git(?P<sha>[0-9a-fA-F]{7})$"
)


logger = logging.getLogger("blossom")

@lru_cache
def warn_once(message: str):
    logger.warning(message)

@dataclass
class GraphPackage:
    name: str
    version: str
    sha: str
    path: str
    apt_depends: List[str]
    source_depends: List[str]
    reverse_depends: List[str] = field(default_factory=list)
    apt_candidate_version: str | None = None
    description: str | None = None
    maintainers: str | None = None

    def __hash__(self):
        return hash(self.path)

    def debian_name(self, organization: str, release_label: str, distribution: str):
        return f"{organization}-{release_label}-{distribution}-{self.name.replace('_', '-')}"

    def debian_version(self, build_date: str):
        return f"{self.version}-{build_date}+git{self.sha}"

    def __post_init__(self):
        if not self.description.endswith("\n"):
            self.description += "\n"

T = TypeVar('T', bound='Graph')

@dataclass
class Graph:
    """
    Class to represent a graph of all packages. This has convenience functions
    for generating a yaml representation of this graph, reading from an existing
    yaml, and generating
    """
    os_name: str
    os_version: str
    distribution: str
    release_label: str
    build_date: str
    packages: Dict[str, GraphPackage] = field(default_factory=dict)
    organization: str = "locusrobotics"

    def __hash__(self):
        return hash(self.name)

    def add_package(self, package: Package, path: Path, sha: str, conditions: Dict[str, Any] = {}):
        if package.name in self.packages:
            raise Exception(f"{package.name} already exists in the graph!")

        dependencies = [
            dep.name for dep in
            package.build_export_depends + package.buildtool_export_depends +
            package.exec_depends + package.build_depends + package.doc_depends +
            package.exec_depends + package.buildtool_depends + package.test_depends +
            package.run_depends
            if dep.evaluate_condition(conditions) or dep.evaluated_condition
        ]

        apt_deps = set()
        source_deps = set()

        for dep in dependencies:
            try:
                definition = self._rosdep_view.lookup(dep)

                rules = definition.get_rule_for_platform(
                    os_name=self.os_name,
                    os_version=self.os_version,
                    installer_keys=["apt"],
                    default_installer_key="apt"
                )

                # Special case here: We have packages which are source packages
                # but also have entries in rosdep.yaml. One example of this is
                # xmlrpcpp which is a ROS1 package but ros1_bridge requires it
                # therefore it needs an entry (empty array) in rosdep.

                if len(rules[1]) == 0 and dep in self.packages:
                    warn_once(f"Dependency {dep} has empty set of rules, but exists"
                                " as a source package")
                    source_deps.add(dep)
                    continue

                if dep in self.packages:
                    warn_once(f"Dependency {dep} was found both as a rosdep and as a source "
                                "package! Adding as a system package only")

                for pkg_apt in rules[1]:
                    # TODO: Sometimes rosdep returns strange package names which
                    #       don't appear to exist.
                    #       e.g. libboost-filesystem resolves to libboost-filesystem1.74.0
                    #if apt_pkg not in self._apt_cache:
                    #    print(f"original dep: {dep}")
                    #    print(rules)
                    #    print(apt_pkg)
                    #    raise Exception(f"Missing APT dependency {apt_pkg}")
                    apt_deps.add(pkg_apt)

            except (KeyError, ResolutionError):
                source_deps.add(dep)

        pkg = GraphPackage(
            package.name,
            package.version,
            sha,
            str(path),
            list(apt_deps),
            list(source_deps),
            description=package.description,
            maintainers=" ".join([str(p) for p in package.maintainers]),
        )

        # Check if there is an APT candidate for the source package
        pkg.apt_candidate_version = self._get_apt_candidate_version(pkg)

        self.packages[package.name] = pkg

        # Calculate reverse depends afterwards

    def _get_apt_candidate_version(self, package: GraphPackage) -> str | None:
        deb_name = package.debian_name(self.organization, self.release_label, self.distribution)

        try:
            deb_pkg = self._apt_cache[deb_name]
        except KeyError:
            return None

        versions = []

        for ver in deb_pkg.versions:
            suites = {origin.archive for origin in ver.origins if origin.archive}
            for suite in suites:
                if suite != self.os_version:
                    continue

                versions.append(ver)

        if len(versions) == 0:
            return None

        # Use Debian version comparison to find the max
        best = versions[0]
        for v in versions[1:]:
            # > 0 means v is newer than best
            if apt_pkg.version_compare(ver.version, best.version) > 0:
                best = v

        return best.version

    def finalize(self):
        for name, package in self.packages.items():
            for depend in package.source_depends:
                if depend not in self.packages:
                    raise Exception(f"Package {depend} was marked as a source dependency to {name}, but it was not found")

                if name not in self.packages[depend].reverse_depends:
                    self.packages[depend].reverse_depends.append(name)

    def _recurse_depends(self, depend: str, visited=None, rdeps=False, apt_depends=False):
        dep_type = "reverse_depends" if rdeps else "source_depends"

        if apt_depends:
            dep_type = "apt_depends"

        if visited is None:
            visited = set()

        if depend in visited:
            return set()

        visited.add(depend)
        d = set()

        for dep in getattr(self.packages[depend], dep_type):
            d.add(dep)
            d.update(self._recurse_depends(dep, visited, rdeps=rdeps))

        return d

    def debian_source_depends(self, package: GraphPackage, build_list: Dict[str, GraphPackage], build_date: str):
        depends = set()

        # APT depends can be set as-is
        for dep in package.apt_depends:
            depends.add(dep)

        # Source depends need to be handled in a way that we can re-use existing
        # APT candidates, but also include any new versions being built in this run
        # hence the need to pass a build list.
        for dep in package.source_depends:
            dep_pkg = self.packages[dep]
            deb_name = dep_pkg.debian_name(self.organization, self.release_label, self.distribution)

            deb_version = self._apt_cache[deb_name].candidate.version

            #if dep not in build_list:
            #    # This dependency is not being rebuilt, reuse existing package
            #    deb_version = dep_pkg.apt_candidate_version
            #else:
            #    # Generate a new version
            #    deb_version = dep_pkg.debian_version(build_date)
            #
            # TODO: When building single package we CANNOT generate a new version
            #       at this point because it won't exist. We have to assume
            #       any dependencies have already been built
            #

            depends.add(f"{deb_name} (= {deb_version})")

        return list(depends)

    @lru_cache
    def all_source_depends(self, package: str, include_apt=False) -> List[str]:
        deps = self._recurse_depends(package, rdeps=False)

        return list(deps)

    @lru_cache
    def all_source_rdepends(self, package: str, include_apt=False) -> List[str]:
        rdeps = self._recurse_depends(package, rdeps=True)

        return list(rdeps)

    def get_depends(self, package: str) -> Tuple[List[str], List[str]]:
        source_names: List[str] = []
        apt_names: List[str] = self.packages[package].apt_depends

        for source_dep in self.packages[package].source_depends:
            dep_pkg = self.packages[source_dep]
            deb_name = dep_pkg.debian_name(self.organization, self.release_label, self.distribution)

            cache_pkg_version = self._apt_cache[deb_name].candidate.version

            #if cache_pkg_version != dep_pkg.apt_candidate_version:
            #    print("mismatch in versions")
            #    print(f"Graph uses: {dep_pkg.apt_candidate_version}")
            #    print(f"APT has: {cache_pkg_version}")

            deb_name += f"={cache_pkg_version}"

            source_names.append(deb_name)

            for apt_dep in self.packages[source_dep].apt_depends:
                apt_names.append(apt_dep)

        return apt_names, source_names

    def all_upstream_depends(self, package: str):
        return self.packages[package].apt_depends

    def package_needs_rebuild(self, package: GraphPackage) -> bool:
        # Otherwise check if the candidates git SHA matches what we have cloned
        deb_name = package.debian_name(self.organization, self.release_label, self.distribution)

        try:
            deb_pkg = self._apt_cache[deb_name]
            apt_version = deb_pkg.candidate.version
        except KeyError:
            return True

        sha = apt_version.split("+git")[-1][:7]
        if sha == package.sha:
            #print(f"{package.name} has already been built ({deb_name}={package.apt_candidate_version})")
            return False

        print(f"Previously built {package.name} SHA {sha} does not match {package.sha}, need to rebuild")

        return True

    def build_list(self, root_packages: List[str], skip_rdeps: bool = False) -> Tuple[Dict[str, GraphPackage], Dict[str, GraphPackage]]:
        """
        From an initial list of packages collect all dependent packages that
        don't already have a build candidate. If a package needs to be rebuilt
        this will also trigger any reverse dependencies to also be added.

        Returns a tuple:
          - The first element is a dictionary of packages which need to be built
          - The second element is a dictionary of packages which already exist in APT
        """
        build_list: Dict[str, GraphPackage] = {}
        download_list: Dict[str, GraphPackage] = {}

        print(f"Building list for {root_packages}")

        @lru_cache
        def add_rdeps(name: str):
            if name not in root_packages:
                return

            rdeps = self.all_source_rdepends(name)

            # If this package is being rebuilt all reverse depends need to
            # also be rebuilt.
            for r in rdeps:
                if r not in root_packages:
                    continue
                if r in build_list:
                    continue
                #print(f"    {r}")
                build_list[r] = self.packages[r]

        if root_packages == []:
            # No packages specified, rebuild all
            root_packages = list(self.packages.keys())
        else:
            # Specific list, add all dependencies of these. This is mostly for
            # testing to build a subset of packages, rather than all.
            for name in root_packages.copy():
                #print(f"getting all source depends for {name}")
                depends = self.all_source_depends(name)
                root_packages.extend(depends)

                root_packages = list(set(root_packages))

        print(f"Generating list of packages to build... {root_packages}")

        for name in root_packages:
            #print(f"Adding deps for {name}")
            package = self.packages[name]

            # Top level packages. If any need to be rebuilt also add rdeps
            if self.package_needs_rebuild(package):
                build_list[name] = package

                if not skip_rdeps:
                    add_rdeps(package.name)
            else:
                print(f"{name} does not need to be rebuilt")
                download_list[name] = package

            # Iterate the entire dependency tree, including nested dependencies
            for dep in self.all_source_depends(name):
                dep_pkg = self.packages[dep]

                if self.package_needs_rebuild(dep_pkg):
                    build_list[dep] = self.packages[dep]

                    if not skip_rdeps:
                        add_rdeps(dep)
                else:
                    build_list[dep] = self.packages[dep]

        return build_list, download_list

    def __post_init__(self):
        self._apt_cache = apt.Cache()

        sources_loader = SourcesListLoader.create_default()
        self._rosdep_lookup = RosdepLookup.create_from_rospkg(
            sources_loader=sources_loader
        )
        self._rosdep_view = self._rosdep_lookup.get_rosdep_view(DEFAULT_VIEW_KEY)

    def write_yaml(self, path: Path):
        if not path.exists():
            path.mkdir(exist_ok=True)

        filename = path / Path(self.name + ".yaml")

        with open(filename, "w") as f:
            yaml.safe_dump(asdict(self), f)

        print(f"Wrote {filename}")

    @classmethod
    def from_yaml(cls, file: Path) -> T:
        data = yaml.safe_load(file.read_text())

        packages: Dict[str, GraphPackage] = {}
        for name, pkg_data in data["packages"].items():
            packages[name] = GraphPackage(**pkg_data)

        data.pop("packages")

        graph = Graph(**data, packages=packages)
        graph.finalize()

        return graph


    @classmethod
    def from_recipe(cls, recipe: Dict, workspace: Path, release_label: str, build_date: str) -> T:
        def _load_repo_jsonl(path: Path):
            repos = {}
            with open(path, "r") as f:
                for line in f.readlines():
                    info = json.loads(line)
                    repos[info['repo']] = info["sha"]
                return repos

        graphs = []

        for os_name, versions in recipe["os"].items():
            for os_version in versions:
                for ros_dist, data in recipe["common"]["distributions"].items():
                    graph = Graph(os_name, os_version, ros_dist, release_label, build_date)

                    # Load the json file with all the repository information. We only need the SHA
                    # hash, so this returns a dictionary containing repo names as keys, and the
                    # SHA hash as values.
                    json_path = workspace / Path("src") / Path(ros_dist) / "repositories_data.jsonl"
                    if not json_path.exists():
                        continue
                    repos = _load_repo_jsonl(json_path)

                    for path, package in topological_order(
                        workspace / Path("src") / Path(ros_dist)
                    ):
                        # The first part of the path should be the repository name. Use this to
                        # index into the repos dict for the SHA hash.
                        repo = Path(path).parts[0]
                        sha = repos[repo][:7]

                        graph.add_package(package, Path(path), sha, conditions=recipe["common"]["distributions"][ros_dist]["env"])

                    # This adds any reverse depends for easier lookup later on.
                    graph.finalize()

                    graphs.append(graph)

        return graphs

    @property
    def name(self):
        return f"{self.os_name}-{self.os_version}-{self.distribution}-graph"

    def _debian_name_to_package(self, name: str) -> str | None:
        try:
            org_start = name.index(self.organization)
            org_end = org_start + len(self.organization)
            org = name[org_start:org_end]
            if org != self.organization:
                return None

            label_start = name.index(self.release_label, org_end + 1)
            label_end = label_start + len(self.release_label)
            label = name[label_start:label_end]
            if label != self.release_label:
                return None

            distro_start = name.index(self.distribution, label_end + 1)
            distro_end = distro_start + len(self.distribution)
            distro = name[distro_start:distro_end]
            if distro != self.distribution:
                return None
        except ValueError:
            return None

        pkg_name = name[distro_end + 1:]

        found = None

        for pkg in self.packages.keys():
            pkg_normalized = pkg.replace("_", "-")
            if pkg_normalized == pkg_name:
                found = pkg
                break

        return found


    @lru_cache
    def _debain_package_exists(self, name: str, version: str) -> Tuple[bool, bool]:
        """
        Checks that a debian package + version exists. First the name is validated
        to ensure it matches the graphs org/release/distro. Then the version is
        checked to ensure it exists already as a debian package.

        Returns a tuple with two booleans:
        bool[0] - The package name/version corresponds to a source package
        bool[1] - The package name/version was found
        """

        #print(f"Checking for debian package {name} ({version})")

        if name == f"{self.organization}-{self.release_label}-{self.distribution}-bootstrap":
            return True, True

        if self._debian_name_to_package(name) is None:
            return False, False

        try:
            deb_pkg = self._apt_cache[name]
        except KeyError:
            #print("No debian found for {name}")
            return True, False

        for v in deb_pkg.versions:
            if self.os_version not in [origin.archive for origin in v.origins]:
                continue

            if apt_pkg.version_compare(v.version, version) == 0:
                return True, True

        #print(f"No version {version} found for {name}")

        return True, False

    @lru_cache
    def _apt_pkg_version_exists(self, name: str, version: str) -> List[Tuple[str, str]]:
        try:
            pkg = self._apt_cache[name]
        except KeyError:
            print(f"No version {version} found for {name}")
            return []

        broken = []

        for v in pkg.versions:
            if self.os_version not in [origin.archive for origin in v.origins]:
                continue

            if apt_pkg.version_compare(v.version, version) != 0:
                continue

            #print(f"{name} was found, checking dependencies")
            broken_dep = False

            depends = v.get_dependencies("Depends")
            for depend in depends:
                for base_depend in depend:
                    #print(f"Checking {base_depend.name}")
                    is_source, exists = self._debain_package_exists(base_depend.name, base_depend.version)
                    if not is_source:
                        continue
                    if exists:
                        continue

                    broken_dep = True
                    print(f"Package {name} dependency {base_depend.name} ({base_depend.version}) doesn't exist")
                    #broken.append((base_depend.name, base_depend.version))

            if broken_dep:
                broken.append((name, version))

        return broken

    def delete_debian(self, deb_name: str, version: str, token: str | None):
        pkg_name = self._debian_name_to_package(deb_name)

        url = f"https://locusbots.jfrog.io/artifactory/locusrobotics-per-package/pool/{self.release_label}/{pkg_name}/{deb_name}_{version}_amd64_{self.os_version}.deb"
        headers = {"Authorization": f"Bearer {token}"}

        if token is None:
            print(f"[DRY-RUN] Would DELETE: {url}")
            return

        resp = requests.delete(url, headers=headers, timeout=60)
        if resp.status_code in (200, 202, 204):
            print(f"Deleted: {url}")
        else:
            print(f"Failed ({resp.status_code}): {resp.text}")


    def cleanup(self, token: str):
        """
        Checks the validity of a graph. If packages were built prior but then
        removed there could be broken dependencies. This is likely only needed
        during development.
        """

        broken = []
        for name, pkg in self.packages.items():
            #if not pkg.apt_candidate_version:
            #    continue

            deb_name = pkg.debian_name(self.organization, self.release_label, self.distribution)

            try:
                package = self._apt_cache[deb_name]
            except KeyError:
                continue

            for version in package.versions:
                broken.extend(self._apt_pkg_version_exists(deb_name, version.version))

        if len(broken) == 0:
            return

        print("Removing missing/broken packages:")
        for name, version in broken:
            self.delete_debian(name, version, token)

        return broken

    @property
    def debian_info(self):
        return self.organization, self.release_label, self.distribution

    def check_apt(self):
        package_versions = {}
        deb_pkgs = {}

        # load up all the top level packages + versions
        for package in self.packages.values():
            deb_name = package.debian_name(*self.debian_info)
            try:
                deb_pkg = self._apt_cache[deb_name]
                deb_pkgs[deb_name] = deb_pkg
                package_versions[deb_name] = deb_pkg.candidate.version
            except KeyError:
                package_versions[deb_name] = None

        broken = {}

        def add_conflict(deb_name, depend):
            dep_name = f"{depend.name}={depend.version}"
            if deb_name not in broken:
                broken[deb_name] = [dep_name]
            else:
                broken[deb_name].append(dep_name)

        # Now iterate again looking at all the apt dependencies (for source packages)
        # and ensure there aren't any conflicts compared to the versions set above
        for deb_name, deb_pkg in deb_pkgs.items():
            for dep in deb_pkg.candidate.dependencies:
                for d in dep:
                    # Ignore deps that aren't our source packages
                    if not d.name.startswith(f"{self.organization}-{self.release_label}-{self.distribution}"):
                        continue
                    # Ignore bootstrap
                    if d.name == f"{self.organization}-{self.release_label}-{self.distribution}-bootstrap":
                        continue

                    if d.name not in deb_pkgs:
                        warn_once(f"{d.name} was listed as a dependency to {deb_name}, but its not in the cache!")
                        add_conflict(deb_name, d)

                    if d.version != deb_pkgs[d.name].candidate.version:
                        warn_once(f"{deb_name} -- {d.name} has version {d.version} which is not in the cache!")
                        add_conflict(deb_name, d)

        for deb_name, depends in broken.items():
            print(f"{deb_name}:")
            for d in depends:
                print(f"    {d}")
@dataclass
class JenkinsJob:
    name: str
    path: str
    depends: List[str]

@dataclass
class DebianGenerator:
    recipe: GlobalRecipe
    graph: Graph

    def generate(self, workspace: Path, packages: List[str] = [], skip_rdeps: bool = False) -> List[JenkinsJob]:
        jobs: List[JenkinsJob] = []

        if packages == []:
            packages = list(self.recipe.root_packages[self.graph.distribution])
            build_list = self.graph.build_list(packages, skip_rdeps=skip_rdeps)
        else:
            build_list = {name: self.graph.packages[name] for name in packages}

        for pkg in sorted(build_list.keys()):
            print(pkg)

        print("Generating debian templates:")
        for name, pkg in build_list.items():
            self.write_templates(pkg, build_list, workspace)

            deb_name = pkg.debian_name(self.graph.organization, self.graph.release_label, self.graph.distribution)

            depends = [
                dep.debian_name(self.graph.organization, self.graph.release_label, self.graph.distribution)
                for dep in build_list.values() if dep.name in pkg.source_depends
            ]

            print(f"Dependencies for {name}: {depends}")

            job = JenkinsJob(
                deb_name,
                pkg.path,
                depends
            )

            jobs.append(job)

        return jobs

    def write_templates(self, package: GraphPackage, build_list: Dict[str, GraphPackage], workspace: Path):
        """Create templates for debian build"""
        env = jinja2.Environment(
            loader=jinja2.PackageLoader("tailor_meta", "debian_templates"),
            undefined=jinja2.StrictUndefined,
            trim_blocks=True,
        )
        env.filters["regex_replace"] = lambda s, find, replace: re.sub(find, replace, s)
        env.filters["union"] = lambda left, right: list(set().union(left, right))

        for template_name in env.list_templates():
            if not template_name.endswith(TEMPLATE_SUFFIX):
                continue

            template_path = Path(debian_templates.__file__).parent / template_name
            output_path = (
                workspace / Path("src") / Path(self.graph.distribution) / package.path / Path("debian") / template_name[: -len(TEMPLATE_SUFFIX)]
            )

            output_path.parent.mkdir(parents=True, exist_ok=True)

            source_depends = self.graph.debian_source_depends(package, build_list, self.recipe.build_date)

            context = dict(
                package_name=package.name,
                distro_name=self.graph.distribution,
                debian_name=package.debian_name(self.recipe.organization, self.recipe.release_label, self.graph.distribution),
                debian_version=package.debian_version(self.recipe.build_date),
                run_depends=package.apt_depends + source_depends,
                src_dir=os.path.abspath(workspace / "src"),
                bucket_name=APT_REPO[len(SCHEME_S3) :],
                bucket_region=APT_REGION,
                os_version=self.recipe.os_version,
                organization=self.recipe.organization,
                release_label=self.recipe.release_label,
                cxx_flags=self.recipe.cxx_flags,
                cxx_standard=self.recipe.cxx_standard,
                python_version="3",
                os_name=self.graph.os_name,
            )

            template = env.get_template(template_name)
            stream = template.stream(**context)
            print(f"Writing {output_path} ...")
            stream.dump(str(output_path))

            current_permissions = stat.S_IMODE(os.lstat(template_path).st_mode)
            os.chmod(output_path, current_permissions)

    def __str__(self):
        return f"""
Package: {self.name}
Version: {self.version}
Depends: {', '.join(self.apt_dependencies + self.source_dependencies)}
Distribution: {self.distribution}
"""

def find_recipe_from_graph(graph: Graph, recipes_dir: Path) -> GlobalRecipe:
    recipes = load_recipes(recipes_dir)

    for recipe in recipes:
        if recipe.os_name != graph.os_name:
            continue
        if recipe.os_version != graph.os_version:
            continue
        if recipe.release_label != graph.release_label:
            continue

        return recipe

    raise Exception("Could not find a recipe matching graph")


def generate_boostrap_templates(graph: Graph):
    """Create templates for debian build"""
    env = jinja2.Environment(
        loader=jinja2.PackageLoader("tailor_meta", "debian_bootstrap_templates"),
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
    )
    env.filters["regex_replace"] = lambda s, find, replace: re.sub(find, replace, s)
    env.filters["union"] = lambda left, right: list(set().union(left, right))
    for template_name in env.list_templates():
        if not template_name.endswith(TEMPLATE_SUFFIX):
            continue

        template_path = Path(debian_templates.__file__).parent / template_name
        output_path = (
            Path("bootstrap") / Path("debian") / template_name[: -len(TEMPLATE_SUFFIX)]
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)

        context = dict(
            distro_name=graph.distribution,
            debian_name=f"{graph.organization}-{graph.release_label}-{graph.distribution}-bootstrap",
            debian_version="0.0.1",
            os_version=graph.os_version,
            organization=graph.organization,
            release_label=graph.release_label,
            os_name=graph.os_name,
        )

        template = env.get_template(template_name)
        stream = template.stream(**context)
        print(f"Writing {output_path} ...")
        stream.dump(str(output_path))

        current_permissions = stat.S_IMODE(os.lstat(template_path).st_mode)
        os.chmod(output_path, current_permissions)

def download_package(package, output_dir):
    subprocess.run(["apt-get", "download", package], cwd=output_dir)


def main():
    parser = argparse.ArgumentParser("blossom")
    parser.add_argument("action")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--recipe", type=Path)
    parser.add_argument("--graph", type=Path)
    parser.add_argument("--packages", nargs='*', type=str, default=[])
    parser.add_argument("--package-path", type=Path)
    parser.add_argument("--skip-rdeps", action='store_true')
    parser.add_argument("--ros-distro", nargs='+', type=str)
    parser.add_argument("--source-prefix")
    parser.add_argument("--token")
    parser.add_argument("--output", type=Path)

    args = parser.parse_args()

    if args.action == "graph":
        graphs = Graph.from_recipes(args.recipe, args.workspace)

        for graph in graphs:
            graph.write_yaml(args.workspace / Path("graphs"))

    elif args.action == "generate":
        graph = Graph.from_yaml(args.graph)
        recipe = find_recipe_from_graph(graph, args.recipe)

        if args.package_path:
            graph.packages[args.packages[0]].path = args.package_path

        generator = DebianGenerator(recipe, graph)
        generator.generate(args.workspace, packages=args.packages, skip_rdeps=True)

    elif args.action == "check-deps":
        graph = Graph.from_yaml(args.graph)
        recipe = find_recipe_from_graph(graph, args.recipe)

        if args.package_path:
            graph.packages[args.packages[0]].path = args.package_path

        built = set()

        for name in graph.packages.keys():
            package = graph.packages[name]

            print(f"Checking if {name} needs to be rebuilt")

            if graph.package_needs_rebuild(package):
                print(f"{name} has changed, rebuild needed")

            # The package itself has not changed, but a dependency might have
            for dep in graph.all_source_depends(name):
                dep_pkg = graph.packages[dep]
                if graph.package_needs_rebuild(dep_pkg):
                    print(f"{dep} has change, this requires a rebuild of {name}")
                else:
                    built.add(dep)

        downloads = []

        for pkg in built:
            gpkg = graph.packages[pkg]
            deb_name = gpkg.debian_name(graph.organization, graph.release_label, graph.distribution)
            deb_version=graph._apt_cache[deb_name].candidate.version

            downloads.append(f"{deb_name}={deb_version}")

        with ThreadPoolExecutor(max_workers=50) as ex:
            futures = [ex.submit(download_package, spec, args.output) for spec in downloads]
            for fut in as_completed(futures):
                fut.result()

    elif args.action == "build":
        graph = Graph.from_yaml(args.graph)
        recipe = find_recipe_from_graph(graph, args.recipe)


        print(recipe.root_packages)

        pkg_list = graph.build_list(recipe.root_packages["ros1"])
        #pkg_list = graph.packages.keys()

        pkgs = {k: v for k, v in graph.packages.items() if k in pkg_list}

        if not isinstance(pkgs, dict) or not pkgs:
            raise ValueError("Input must contain a non-empty 'packages' dictionary")

        # Preserve original input order as a stable tie-breaker.
        original_order = list(pkgs.keys())
        order_index = {name: i for i, name in enumerate(original_order)}

        # Build in-repo dependency graph: edges from dep -> pkg (dep must precede pkg)
        names = set(pkgs.keys())
        out_edges = defaultdict(set)   # dep -> {pkg, ...}
        indegree = {name: 0 for name in names}

        for pkg_name, meta in pkgs.items():
            deps = meta.source_depends
            for dep in deps:
                if dep in names:
                    out_edges[dep].add(pkg_name)
                    indegree[pkg_name] += 1
            # Ensure node exists in out_edges even if it has no outgoing edges
            out_edges[pkg_name] |= set()

        # Kahn's algorithm but grouped into layers
        # Start with nodes that have indegree 0 (no in-repo deps), sorted by original input order.
        zero_in = [n for n, deg in indegree.items() if deg == 0]
        zero_in.sort(key=lambda n: order_index.get(n, float("inf")))

        layers = []
        removed = 0

        while zero_in:
            # Current layer is everything that just became ready
            layer = zero_in
            layers.append(layer)

            # Remove this layer and update indegrees
            next_zero = []
            for n in layer:
                removed += 1
                for m in out_edges[n]:
                    indegree[m] -= 1
                    if indegree[m] == 0:
                        next_zero.append(m)

            # Next layer: sort by original order for determinism
            next_zero.sort(key=lambda n: order_index.get(n, float("inf")))
            zero_in = next_zero

        if removed != len(names):
            # Cycle detected: collect remaining nodes and a hint of cyclic edges
            remaining = [n for n in names if indegree[n] > 0]
            msg = (
                "Dependency cycle detected among packages: "
                + ", ".join(sorted(remaining, key=lambda n: order_index[n]))
            )
            raise RuntimeError(msg)

        for layer in layers:
            print(layer)

        output: Path = args.output
        output.write_text(json.dumps(layers))


    elif args.action == "test":
        graph = Graph.from_yaml(args.graph)
        recipe = find_recipe_from_graph(graph, args.recipe)

        generator = DebianGenerator(recipe, graph)
        jobs = generator.generate(args.workspace, packages=args.packages, skip_rdeps=args.skip_rdeps)

        for job in jobs:
            if job.depends == []:
                print(f"{job.name} has no deps!")

        done = []
        pending = []

        def deps_met(job: JenkinsJob):
            if job.name == "locusrobotics-build-per-package-ros1-rosmake":
                print(f"Checking {job.name}, deps={job.depends}")
                print(f"Done={done}")

            for dep in job.depends:
                if dep not in done:
                    return False

            return True

        while len(jobs) > 0:
            for job in jobs.copy():
                if deps_met(job):
                    print(f"Adding {job.name} to pending list")
                    pending.append(job)
                    jobs.remove(job)
                else:
                    #print(f"{job.name} has unmet dependencies: {job.depends}")
                    pass

            if len(pending) == 0:
                print("No more jobs to run")
                return

            current = pending.pop(0)

            #print(f"Pretending to build: {current.name}")

            subprocess.run(
                ['fakeroot', 'debian/rules', 'binary'],
                cwd=args.workspace / Path("src") / Path(graph.distribution) / current.path,
                check=True,
            )

            done.append(current.name)
    elif args.action == "install":
        install_list = []

        graph = Graph.from_yaml(args.graph)
        for pkg in args.packages:
            upstream, source = graph.get_depends(pkg)
            #print(f"Upstream deps: {upstream}")
            #print(f"Source deps: {source}")
            install_list.extend(upstream)
            #install_list.extend(source)

        print(" ".join(install_list))

    elif args.action == "sources":
        sources = []

        graph = Graph.from_yaml(args.graph)
        for pkg in args.packages:
            upstream, source_deps = graph.get_depends(pkg)

            sources.extend(source_deps)

        print(" ".join(sources))

    elif args.action == "bootstrap":
        graph = Graph.from_yaml(args.graph)

        generate_boostrap_templates(graph)
    elif args.action == "check-apt":
        graphs: List[Graph] = []

        print(f"Loading graph(s) from: {args.graph}")

        if args.graph.is_dir():
            for graph in args.graph.iterdir():
                graphs.append(Graph.from_yaml(graph))
        else:
            graphs.append(Graph.from_yaml(args.graph))

        broken = False

        for graph in graphs:
            print(f"Checking graph: {graph.name}")
            graph.check_apt()

    elif args.action == "check":
        package_list = {}
        delete_list = {}

        @lru_cache
        def recurse_package(graph: Graph, package, version):
            if not package.startswith("locusrobotics"):
                return

            deb_pkg = graph._apt_cache[package]

            for v in deb_pkg.versions:
                if v != version:
                    continue

                for dep in v.dependencies:
                    for d in dep:
                        if d.name in package_list and package_list[d.name] != d.version:
                            #warn_once(f"Package: {d.name} conflicts {d.version} ... {package_list[d.name]}")
                            #graph.delete_debian(d.name, d.version, args.token)
                            delete_list[d.name] = d.version
                        else:
                            package_list[d.name] = d.version
                        recurse_package(graph, d.name, d.version)

        graphs: List[Graph] = []

        print(f"Loading graph(s) from: {args.graph}")

        if args.graph.is_dir():
            for graph in args.graph.iterdir():
                graphs.append(Graph.from_yaml(graph))
        else:
            graphs.append(Graph.from_yaml(args.graph))

        broken = False

        for graph in graphs:
            print(f"Checking graph: {graph.name}")

#            pkg_list = []
#
#            if args.packages:
#                packages = args.packages
#            else:
#                packages = graph.packages.keys()
#
#            dependency_list = {}
#
#            for pkg in packages:
#                pkg = graph.packages[pkg]
#                deb_name = pkg.debian_name(graph.organization, graph.release_label, graph.distribution)
#                deb_pkg = graph._apt_cache[deb_name]
#
#                for v in deb_pkg.versions:
#                    recurse_package(graph, deb_name, v.version)
#
#            for p, v in delete_list.items():
#                graph.delete_debian(p, v, args.token)

            if graph.cleanup(args.token) != []:
                broken = True

        if broken:
            exit(1)

        exit(0)


if __name__ == "__main__":
    main()

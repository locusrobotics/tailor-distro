import apt_pkg
import yaml
import logging
import json

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

from .apt_tools import AptSandbox

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
    ros_version: str
    apt_depends: List[str]
    source_depends: List[str]
    ros1_depends: List[str] = field(default_factory=list)
    reverse_depends: List[str] = field(default_factory=list)
    ros2_reverse_depends: List[str] = field(default_factory=list)
    apt_candidate_version: str | None = None
    description: str | None = None
    maintainers: str | None = None

    def __hash__(self):
        return hash(self.path)

    def debian_name(self, organization: str, release_label: str):
        return f"{organization}-{release_label}-{self.ros_version}-{self.name.replace('_', '-')}"

    def debian_version(self, build_date: str):
        return f"{self.version}-{build_date}+git{self.sha}"

    def __post_init__(self):
        if self.description and not self.description.endswith("\n"):
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
    release_label: str
    build_date: str
    apt_repo: str
    packages: Dict[str, Dict[str, GraphPackage]] = field(default_factory=dict)
    organization: str = "locusrobotics"
    apt_configs: List[Path] = field(default_factory=list)
    init_apt: bool = True

    def __hash__(self):
        return hash(self.name)

    def add_package(self, package: Package, ros_distro: str, path: Path, sha: str, conditions: Dict[str, Any] = {}):
        if ros_distro not in self.packages:
            self.packages[ros_distro] = {}

        packages = self.packages[ros_distro]

        if package.name in packages:
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
        # Only for ROS2 packages that have ros1 dependencies
        ros1_deps = set()

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

                if len(rules[1]) == 0 and dep in packages:
                    warn_once(f"Dependency {dep} has empty set of rules, but exists"
                                " as a source package")
                    source_deps.add(dep)
                    continue

                if dep in packages:
                    warn_once(f"Dependency {dep} was found both as a rosdep and as a source "
                                "package! Adding as a system package only")

                for pkg_apt in rules[1]:
                    # TODO: Sometimes rosdep returns strange package names which
                    #       don't appear to exist.
                    #       e.g. libboost-filesystem resolves to libboost-filesystem1.74.0
                    apt_deps.add(pkg_apt)

            except (KeyError, ResolutionError):
                source_deps.add(dep)

        for export in package.exports:
            if export.tagname == "ros1_depend":
                ros1_deps.add(export.content)

        pkg = GraphPackage(
            package.name,
            package.version,
            sha,
            str(path),
            ros_distro,
            list(apt_deps),
            list(source_deps),
            ros1_depends=list(ros1_deps),
            description=package.description,
            maintainers=" ".join([str(p) for p in package.maintainers]),
        )

        # Check if there is an APT candidate for the source package
        pkg.apt_candidate_version = self._get_apt_candidate_version(pkg)

        self.packages[ros_distro][package.name] = pkg

        # Calculate reverse depends afterwards

    def _get_apt_candidate_version(self, package: GraphPackage) -> str | None:
        if not self.init_apt:
            return None

        deb_name = package.debian_name(self.organization, self.release_label)

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
        for distro, packages in self.packages.items():
            for name, package in packages.items():
                for depend in package.source_depends:
                    if depend not in packages:
                        raise Exception(f"Package {depend} was marked as a source dependency to {name}, but it was not found")

                    if name not in packages[depend].reverse_depends:
                        self.packages[distro][depend].reverse_depends.append(name)
                for depend in package.ros1_depends:
                    if depend not in self.packages["ros1"]:
                        raise Exception(f"Package {depend} was marked as a ROS1 dependency to {name}, but it was not found")

                    if name not in self.packages["ros1"][depend].ros2_reverse_depends:
                        self.packages["ros1"][depend].ros2_reverse_depends.append(name)

    def _recurse_depends(self, depend: str, ros_distro: str, visited=None, rdeps=False, apt_depends=False):
        dep_type = "reverse_depends" if rdeps else "source_depends"

        if apt_depends:
            dep_type = "apt_depends"

        if visited is None:
            visited = set()

        if depend in visited:
            return set()

        visited.add(depend)
        d = set()

        for dep in getattr(self.packages[ros_distro][depend], dep_type):
            d.add(dep)
            d.update(self._recurse_depends(dep, ros_distro, visited, rdeps=rdeps))

        return d

    @lru_cache
    def all_source_depends(self, package: str, ros_distro: str, include_apt=False) -> List[str]:
        deps = self._recurse_depends(package, ros_distro, rdeps=False)

        return list(deps)

    @lru_cache
    def all_source_rdepends(self, package: str, ros_distro: str, include_apt=False) -> List[str]:
        rdeps = self._recurse_depends(package, ros_distro, rdeps=True)

        return list(rdeps)

    @lru_cache
    def package_needs_rebuild(self, package: GraphPackage) -> bool:
        # Otherwise check if the candidates git SHA matches what we have cloned
        #deb_name = package.debian_name(self.organization, self.release_label, self.distribution)
        apt_version = package.apt_candidate_version
        if not apt_version:
            return True
        #try:
        #    deb_pkg = self._apt_cache[deb_name]
        #    apt_version = deb_pkg.candidate.version
        #except KeyError:
        #    return True

        sha = apt_version.split("+git")[-1][:7]
        if sha == package.sha:
            #print(f"{package.name} has already been built ({deb_name}={package.apt_candidate_version})")
            return False

        warn_once(f"Previously built {package.name} SHA {sha} does not match {package.sha}, need to rebuild")

        return True

    def build_list(self, ros_distro: str, root_packages: List[str] = [], skip_rdeps: bool = False, rebuild_all: bool = True) -> Tuple[Dict[str, GraphPackage], Dict[str, GraphPackage]]:
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

        print(f"Building list for {ros_distro} {root_packages}")

        @lru_cache
        def add_rdeps(name: str):
            if name not in root_packages:
                return

            rdeps = self.all_source_rdepends(name, ros_distro)

            # If this package is being rebuilt all reverse depends need to
            # also be rebuilt.
            for r in rdeps:
                if r not in root_packages:
                    continue
                if r in build_list:
                    continue
                #print(f"    {r}")
                build_list[r] = self.packages[ros_distro][r]

        if root_packages == []:
            # No packages specified, rebuild all
            root_packages = list(self.packages[ros_distro].keys())
        else:
            # Specific list, add all dependencies of these. This is mostly for
            # testing to build a subset of packages, rather than all.
            for name in root_packages.copy():
                #print(f"getting all source depends for {name}")
                depends = self.all_source_depends(name, ros_distro)
                root_packages.extend(depends)

                root_packages = list(set(root_packages))

        print(f"Generating list of packages to build... {root_packages}")

        for name in root_packages:
            package = self.packages[ros_distro][name]

            # Top level packages. If any need to be rebuilt also add rdeps
            if self.package_needs_rebuild(package) or rebuild_all:
                build_list[name] = package

                if not skip_rdeps:
                    add_rdeps(package.name)
            else:
                print(f"{name} does not need to be rebuilt")
                download_list[name] = package

            # Iterate the entire dependency tree, including nested dependencies
            for dep in self.all_source_depends(name, ros_distro):
                dep_pkg = self.packages[ros_distro][dep]
                if self.package_needs_rebuild(dep_pkg) or rebuild_all:
                    build_list[dep] = self.packages[ros_distro][dep]

                    if not skip_rdeps:
                        add_rdeps(dep)
                else:
                    download_list[dep] = self.packages[ros_distro][dep]

        return build_list, download_list

    def __post_init__(self):
        # For loading graphs from yaml we don't have all the info we need to initialize the
        # apt sandbox. Its only when the graph is created where we need to utilize the apt
        # sandbox. From that point on a graph should contain the candidate versions for the
        # packages if they exist.
        if self.init_apt:
            sources = [
                f"deb [arch=amd64 trusted=yes] {self.apt_repo}/{self.release_label}/ubuntu {self.os_version} main",
                f"deb [arch=amd64 trusted=yes] {self.apt_repo}/{self.release_label}/ubuntu {self.os_version}-mirror {self.os_version}"
            ]

            self._apt_sandbox = AptSandbox(sources, local_configs=self.apt_configs)
            self._apt_cache = self._apt_sandbox.cache

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

        packages: Dict[str, Dict[str, GraphPackage]] = {}

        for ros_distro, distro_pkgs in data["packages"].items():
            if ros_distro not in packages:
                packages[ros_distro] = {}

            for name, pkg_data in distro_pkgs.items():
                packages[ros_distro][name] = GraphPackage(**pkg_data)

        data.pop("packages")
        data.pop("init_apt")

        graph = Graph(**data, init_apt=False, packages=packages)
        graph.finalize()

        return graph


    @classmethod
    def from_recipe(cls, recipe: Dict, workspace: Path, release_label: str, build_date: str, apt_configs: List[Path] = [], init_apt: bool = True) -> T:
        def _load_repo_jsonl(path: Path):
            repos = {}
            with open(path, "r") as f:
                for line in f.readlines():
                    info = json.loads(line)
                    repos[info['repo']] = info["sha"]
                return repos

        graphs = []

        apt_repo = recipe["common"]["apt_repo"]

        for os_name, versions in recipe["os"].items():
            for os_version in versions:
                graph = Graph(os_name, os_version, release_label, build_date, apt_repo, apt_configs=apt_configs, init_apt=init_apt)

                for ros_dist, data in recipe["common"]["distributions"].items():
                    #graph = Graph(os_name, os_version, ros_dist, release_label, build_date, apt_repo, apt_configs=apt_configs)

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

                        graph.add_package(package, ros_dist, Path(path), sha, conditions=recipe["common"]["distributions"][ros_dist]["env"])

                # This adds any reverse depends for easier lookup later on.
                graph.finalize()

                graphs.append(graph)

        return graphs

    @property
    def name(self):
        return f"{self.os_name}-{self.os_version}-graph"

    @property
    def debian_info(self):
        return self.organization, self.release_label

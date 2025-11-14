import argparse
import apt
import jinja2
import os
import stat
import re
import yaml

from datetime import datetime
from functools import cache, lru_cache
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import (
    Mapping,
    Tuple,
    Set,
    List,
    Dict,
    Any
)
from catkin_pkg.topological_order import topological_order
from catkin_pkg.package import Package
from rosdep2.sources_list import SourcesListLoader
from rosdep2.lookup import RosdepLookup
from rosdep2.rospkg_loader import DEFAULT_VIEW_KEY

from . import debian_templates
from .recipes import load_recipes, GlobalRecipe

TEMPLATE_SUFFIX = ".j2"
SCHEME_S3 = "s3://"
APT_REGION = os.environ.get("LOCUS_APT_REGION", "us-east-1")
APT_REPO = os.environ.get("LOCUS_APT_REPO", "s3://locus-tailor-artifacts")

@dataclass
class GraphPackage:
    version: str
    sha: str
    path: str
    depends: List[str]
    reverse_depends: List[str] = field(default_factory=list)

@dataclass
class Graph:
    os_name: str
    os_version: str
    distribution: str
    packages: Dict[str, GraphPackage] = field(default_factory=dict)

    def add_package(self, package: Package, path: Path, conditions: Dict[str, Any] = {}):
        if package.name in self.packages:
            raise Exception(f"{package.name} already exists in the graph!")

        folder = path.parts[1]
        sha = folder.split("-")[-1][:7]

        dependencies = [
            dep.name for dep in
            package.build_export_depends + package.buildtool_export_depends +
            package.exec_depends + package.build_depends + package.doc_depends +
            package.exec_depends
            if dep.evaluate_condition(conditions)
        ]

        self.packages[package.name] = GraphPackage(
            package.version,
            sha,
            str(path),
            dependencies
        )

        # Calculate reverse depends afterwards

    def finalize(self):
        for name, package in self.packages.items():
            for depend in package.depends:
                # Must be an external (APT) dependency
                if depend not in self.packages:
                    continue

                if name not in self.packages[depend].reverse_depends:
                    self.packages[depend].reverse_depends.append(name)

    def write_yaml(self, path: Path):
        if not path.exists():
            path.mkdir(exist_ok=True)

        with open(path / Path(f"{self.os_name}-{self.os_version}-{self.distribution}-graph.yaml"), "w") as f:
            yaml.safe_dump(asdict(self), f)

@dataclass
class Debian:
    name: str
    pkg_name: str
    version: str
    path: Path
    # Separating APT/source deps since Jenkins jobs won't need to wait for
    # APT dependencies, but only source deps.
    apt_dependencies: List[str]
    source_dependencies: List[str]
    distribution: str
    workspace: Path
    os_version: str
    organization: str
    release_label: str
    cxx_flags: List[str]
    cxx_standard: str

    def write_template(self):
        """Create templates for debian build"""
        env = jinja2.Environment(
            loader=jinja2.PackageLoader("tailor_distro", "debian_templates"),
            undefined=jinja2.StrictUndefined,
            trim_blocks=True,
        )
        env.filters["regex_replace"] = lambda s, find, replace: re.sub(find, replace, s)
        env.filters["union"] = lambda left, right: list(set().union(left, right))

        for template_name in env.list_templates():
            if (
                not template_name.endswith(TEMPLATE_SUFFIX)
                or "Dockerfile" in template_name
            ):
                continue
            template_path = Path(debian_templates.__file__).parent / template_name
            output_path = (
                self.path / Path("debian") / template_name[: -len(TEMPLATE_SUFFIX)]
            )

            output_path.parent.mkdir(parents=True, exist_ok=True)

            context = dict(
                package_name=self.pkg_name,
                distro_name=self.distribution,
                debian_name=self.name,
                run_depends=self.apt_dependencies + self.source_dependencies,
                src_dir=os.path.abspath(self.workspace / "src"),
                bucket_name=APT_REPO[len(SCHEME_S3) :],
                bucket_region=APT_REGION,
                debian_version=self.version,
                os_version=self.os_version,
                organization=self.organization,
                release_label=self.release_label,
                cxx_flags=self.cxx_flags,
                cxx_standard=self.cxx_standard,
                python_version="3",
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


class Blossom:
    def __init__(self, workspace: Path, recipes: Path) -> None:
        self._workspace = workspace
        self._recipes = load_recipes(recipes)
        self.packages: Dict[str, Mapping[str, Package]] = {}
        self._apt_cache = apt.Cache()
        self.reverse_depends: Dict[str, Dict[str, Set[str]]] = {}
        self.graph: Dict[str, Any]

        sources_loader = SourcesListLoader.create_default()
        self._rosdep_lookup = RosdepLookup.create_from_rospkg(
            sources_loader=sources_loader
        )
        self._rosdep_view = self._rosdep_lookup.get_rosdep_view(DEFAULT_VIEW_KEY)

    def generate_graphs(self):
        # Load all packages and their descriptions (processed package.xml)
        for recipe in self._recipes:
            for distribution in recipe.distributions.keys():
                print(recipe.distributions[distribution].env)
                graph = Graph(recipe.os_name, recipe.os_version, distribution)
                print(f"graph for {recipe.os_name}-{recipe.os_version}-{distribution}")

                # First gather up all packages
                for path, package in topological_order(
                    self._workspace / Path("src") / Path(distribution)
                ):
                    graph.add_package(package, Path(path), conditions=recipe.distributions[distribution].env)

                graph.finalize()

                graph.write_yaml(self._workspace / "graphs")

    def get_debian_depends(self, package: Package):
        return {
            d
            for d in package.build_export_depends
            + package.buildtool_export_depends
            + package.exec_depends
            if d.evaluated_condition
        }

    def get_debian_build_depends(self, package: Package):
        deps = (
            package.build_depends
            + package.doc_depends
            + package.test_depends
            + package.buildtool_depends
        )
        deps += package.build_export_depends + package.buildtool_export_depends
        return {d for d in deps if d.evaluated_condition}

    def get_all_debian_depends(self, package: Package):
        return self.get_debian_depends(package) | self.get_debian_build_depends(package)

    def get_package_sha(self, package: Package, distribution: str) -> str:
        source_dir = Path(package.filename).parent

        # Since multiple packages can be contained in a single repo we need to
        # find the folder that contains the git SHA. Use the workspace path to
        # get the folder index of the directory, then + 1 to get the folder
        # who's name is of the format <org>-<package>-<sha>
        prefix_len = len((self._workspace / Path("src") / Path(distribution)).parents)

        repo_folder = source_dir.parts[prefix_len + 1]
        return repo_folder.split("-")[-1][:7]

    def get_package_debian_name(self, recipe: GlobalRecipe, package: Package) -> str:
        return f"{recipe.organization}-{recipe.release_label}-{package.name.replace('_', '-')}"

    @cache
    def get_package_debian_info(
        self, recipe: GlobalRecipe, distribution: str, package: Package
    ) -> Tuple[str, str, Path]:
        """
        Returns a debian name, debian version, and source directory for the package
        """
        source_dir = Path(package.filename).parent

        sha = self.get_package_sha(package, distribution)
        deb_name = self.get_package_debian_name(recipe, package)
        deb_version = (
            f"{package.version}-{recipe.build_date}+git{sha}"
        )

        return deb_name, deb_version, source_dir

    def package_to_debian(
        self, recipe: GlobalRecipe, distribution: str, package: Package
    ) -> Debian:
        deb_name, deb_version, src_path = self.get_package_debian_info(
            recipe, distribution, package
        )

        apt_deps, src_deps = self.get_dependencies(recipe, distribution, package)

        source_dependencies = []

        # Source dependencies need to be transformed into the correct name
        for dep in src_deps:
            dep_name, dep_version, _ = self.get_package_debian_info(
                recipe, distribution, dep
            )

            # TODO (jprestwood):
            # Are we going to require >= for packages? Or are we going to allow
            # to install older versions of packages manually?
            source_dependencies.append(f"{dep_name} (>= {dep_version})")

        return Debian(
            deb_name,
            package.name,
            deb_version,
            src_path,
            apt_deps,
            source_dependencies,
            distribution,
            self._workspace,
            recipe.os_version,
            recipe.organization,
            recipe.release_label,
            recipe.cxx_flags,
            recipe.cxx_standard,
        )

    def package_needs_rebuild(
        self, recipe: GlobalRecipe, distribution: str, package: Package
    ) -> bool:
        """
        Checks whether a ROS package needs to be re-built into a debain. If
        there is already a debian built from prior builds and there have
        been no source changes there is no need to rebuild
        """
        src_sha = self.get_package_sha(package, distribution)
        deb_name = self.get_package_debian_name(recipe, package)

        try:
            pkg = self._apt_cache[deb_name]

        except KeyError:
            # No package at all
            return True

        if not pkg.candidate:
            print("WARN: No package candidate?")
            return True

        # Check to ensure the version of the previous build matches the SHA
        deb_sha = pkg.candidate.version.split("+git")[-1][:7]

        if deb_sha == src_sha:
            print(
                f"    {package.name} has already been built ({deb_name}={pkg.candidate.version})"
            )
            return False

        print(
            f"    Previously built {package.name} SHA {deb_sha} does not match {src_sha}, need to rebuild"
        )

        return True

    def search_workspaces(
        self,
    ) -> Dict[str, Dict[str, Dict[str, Mapping[str, Debian]]]]:
        """
        Searches workspaces for packages and returns a dictionary:
        os_name:                # e.g. "ubuntu"
          os_version:           # e.g. "jammy" or "noble"
            distro:             # "ros1" or "ros2"
              pkgs...           # dictionary of packages
        """
        ret: Dict[str, Dict[str, Dict[str, Mapping[str, Debian]]]] = {}
        start = datetime.now()

        for recipe in self._recipes:
            if recipe.os_name not in ret:
                ret[recipe.os_name] = {}

            ret[recipe.os_name][recipe.os_version] = {}

            for distribution, packages in recipe.root_packages.items():
                print(
                    f"Searching workspace (os_name={recipe.os_name}, os_version={recipe.os_version}, distribution={distribution}"
                )
                os_name, os_version, distro, debians = self.search_workspace(
                    recipe, distribution, packages
                )
                ret[os_name][os_version][distro] = debians

        elapsed = datetime.now() - start
        print(f"Took {elapsed.total_seconds()} seconds to search workspaces")

        return ret

    def add_reverse_dependency(self, distribution: str, dependency: str, package: str):
        if not self.reverse_depends[distribution].get(dependency, None):
            self.reverse_depends[distribution][dependency] = set()

        self.reverse_depends[distribution][dependency].add(package)

    def search_workspace(
        self, recipe: GlobalRecipe, distribution: str, root_packages: Set[str]
    ) -> Tuple[str, str, str, Mapping[str, Debian]]:
        """
        Get a list of all packages in a workspace. Optionally filter to only include direct dependencies of a
        root package list.
        """
        if root_packages is None:
            return {}

        packages = {}
        self.reverse_depends[distribution] = {}

        # Load all packages and their descriptions (processed package.xml)
        for package in topological_order(
            str(self._workspace / Path("src") / Path(distribution))
        ):
            packages[package[1].name] = package[1]

        if root_packages == []:
            return recipe.os_name, recipe.os_version, distribution, {}

        # Traverse the dependency tree starting with root_packages
        queued = set(root_packages)
        processed = set()
        filtered = set()

        while queued:
            package = queued.pop()
            processed.add(package)
            try:
                package_description = packages[package]
                filtered.add(package)
            except KeyError:
                continue

            for dependency in self.get_all_debian_depends(package_description):
                if dependency.name not in processed:
                    queued.add(dependency.name)
                # Build up an reverse dependency graph because using rosdep to
                # lookup is SLOW.
                self.add_reverse_dependency(distribution, dependency.name, package)

        self.packages[distribution] = {
            package: packages[package] for package in filtered
        }

        return (
            recipe.os_name,
            recipe.os_version,
            distribution,
            self.process_to_debians(recipe, distribution, filtered, packages),
        )

    def process_to_debians(
        self, recipe: GlobalRecipe, distribution: str, filtered: set, packages: dict
    ):
        print(f"Generating build list ({distribution}):")
        debians = {}

        for package in filtered:
            # Skip if no rebuild needed
            if not self.package_needs_rebuild(recipe, distribution, packages[package]):
                continue

            # Add main package
            debians[package] = self.package_to_debian(
                recipe, distribution, packages[package]
            )
            print(f"PKG: {package}")

            # Get reverse dependencies
            rdepends = self.get_rdependencies(package, distribution)
            for rdepend in rdepends:
                if rdepend in debians:
                    continue

                if not self.package_is_source(rdepend, distribution):
                    continue

                debians[rdepend] = self.package_to_debian(
                    recipe, distribution, packages[rdepend]
                )
                print(f"    RDEP:{rdepend}")

        return debians

    def get_rdependencies(self, package: str, distribution: str):
        visited = set()
        stack = [package]
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            stack.extend(self.reverse_depends[distribution].get(current, []))
        visited.discard(package)  # Remove root
        return visited

    @lru_cache(maxsize=None)
    def package_is_source(self, package: str, distribution: str) -> bool:
        # The quick check, if we have this package tracked its a source package
        if package in self.packages[distribution]:
            return True

        # Fail hard if a dependency is not met
        try:
            self._rosdep_view.lookup(package)
            return False
        except KeyError:
            raise Exception(
                f"Unable to find {package} as a system package or a source package!"
            )

    def get_dependencies(
        self,
        recipe: GlobalRecipe,
        distribution: str,
        package: Package,
    ) -> Tuple[List[str], List[Package]]:
        """
        Finds top level dependencies for a package. Returns a tuple with debian package names as
        the first element, and a list of Package objects as the second Tuple element
        """
        if self.packages[distribution] == {}:
            raise Exception(
                "No source packages have been found, was search_workspace() called?"
            )

        dependencies: Set[str] = set()

        # Gather up all top level dependencies in package.xml
        for dep in self.get_all_debian_depends(package):
            if dep.evaluate_condition(recipe.distributions[distribution].env):
                dependencies.add(dep.name)

        apt_deps: Set[str] = set()
        source_deps: Set[Package] = set()

        for dep in dependencies:
            if self.package_is_source(dep, distribution):
                source_deps.add(self.packages[distribution][dep])
            else:
                apt_deps.add(dep)

        return list(apt_deps), list(source_deps)


def main():
    parser = argparse.ArgumentParser("blossom")
    parser.add_argument("action")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--recipe", type=Path)
    parser.add_argument("--graph", type=Path)
    parser.add_argument("--packages", nargs='+')

    args = parser.parse_args()

    if args.action == "parse":
        blossom = Blossom(args.workspace, args.recipe)
        packages = blossom.search_workspaces()

        # TODO (jprestwood):
        # We now have a list of noble/jammy each with ros1 and ros2. We may potentially
        # need to generate separate templates for each OS version? Or can we utilize
        # OS_DISTRO (or some env vars) within the template to be agnostic?

        for os_name, os_data in packages.items():
            for os_version, version_data in os_data.items():
                for distribution, distro_debians in version_data.items():
                    for package, debian in distro_debians.items():
                        debian.write_template()
    elif args.action == "graph":
        blossom = Blossom(args.workspace, args.recipe)
        blossom.generate_graphs()
    elif args.action == "build":
        graph = yaml.safe_load(args.graph.read_text())

        rdepends = set()

        def recurse_depends(depend: str, visited=None):
            if visited is None:
                visited = set()

            # Avoid cycles
            if depend in visited:
                return set()

            visited.add(depend)
            d = set()

            for dep in graph["packages"][depend]["reverse_depends"]:
                d.add(dep)
                d.update(recurse_depends(dep, visited))  # Recursive call

            return d

        print("Packages requested to build:")
        for package in args.packages:
            print(f"Package: {package}")

            rdepends = recurse_depends(package)

            print("  Reverse Depends:")
            for rdep in rdepends:
                print(f"    {rdep}")

if __name__ == "__main__":
    main()

import os
import shutil
import math

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from colcon_core.event_handler import EventHandlerExtensionPoint
from colcon_core.event.job import JobEnded
from colcon_core.plugin_system import satisfies_version
from colcon_core.event_reactor import EventReactorShutdown

from tailor_distro.blossom import Graph

from . import fix_local_paths, package_debian

PACKAGING_THREADS = 4
IGNORE_PATTERNS = [".catkin"]


def size2str(size: int) -> str:
    if size == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size, 1024)))
    p = math.pow(1024, i)
    s = round(size / p, 2)
    return f"{s} {size_name[i]}"


def calculate_size(path: str) -> str:
    def _calculate_size(path: str) -> int:
        total_size = 0
        for entry in os.scandir(path):
            if entry.is_file():
                total_size += entry.stat().st_size
            elif entry.is_dir():
                total_size += _calculate_size(entry.path)

        return total_size

    return size2str(_calculate_size(path))



class DebianPackager(EventHandlerExtensionPoint):
    ENABLED_BY_DEFAULT = False

    def __init__(self):
        super().__init__()

        satisfies_version(
            EventHandlerExtensionPoint.EXTENSION_POINT_VERSION, '^1.0'
        )

        if "ROS_PACKAGING_GRAPH" not in os.environ:
            # There is no way to detect if colcon was called with this event handler
            # within __init__. All we can do is warn, then disable this extension.
            print("ROS_PACKAGING_GRAPH not set, will not enable debian_packager event handler")
            self.enabled = False
            return

        # TODO (jprestwood):
        # There are a number of paths we need in order to package:
        #  - Path of the workspace, or at least some directory where we can copy
        #    install artifacts and generate a debian /opt structure
        #  - Path of the graph yaml file (e.g. workspace/graphs/<graph>.yaml)
        #
        # We need to figure out how to pass this in via custom arguments. Nothing
        # found online works, and there is little to no documentation around any
        # of these extension classes.
        self._graph = Graph.from_yaml(Path(os.environ["ROS_PACKAGING_GRAPH"]))

        self.enabled = DebianPackager.ENABLED_BY_DEFAULT

        # Copy install files to a new workspace that mirrors how packages will
        # be installed. This is required as the non --merge-install build isolates
        # packages, which in turn requires 700+ individual paths to be defined
        # in the environment. By copying here we're effectively merging all the
        # packages after the fact, which allows us to define a single path to the
        # workspace (ROS_PACKAGE_PATH/PYTHONPATH/LD_LIBRARY_PATH/etc)
        install = Path("optinstall")
        install.mkdir(exist_ok=True)

        self._optinstall = (
            install
            / self._graph.organization
            / self._graph.release_label
            / self._graph.distribution
        )
        self._optinstall.mkdir(parents=True, exist_ok=True)

        # Create a thread pool for packaging
        self._packaging_executor = ThreadPoolExecutor(max_workers=PACKAGING_THREADS)
        self._futures = []
        self._errors = []

        print("Initialized packager plugin")

    def __call__(self, event):
        data = event[0]
        job = event[1]

        # Final event that colcon is shutting down, wait for packaging to finish
        if isinstance(data, EventReactorShutdown) and self.enabled:
            for f in as_completed(self._futures):
                try:
                    f.result()
                except Exception as e:
                    self._errors.append(e)

            if self._errors:
                raise Exception(f"Errors encountered during packaging: {self._errors}")

            return

        # Ignore any other events except package completion
        if not (isinstance(data, JobEnded) and self.enabled):
            return

        pkg_path = job.task_context.args.install_base
        pkg_name = data.identifier

        self._futures.append(
            self._packaging_executor.submit(
                self.package_debian, pkg_name, pkg_path
            )
        )

    def package_debian(self, name: str, path: Path):
        print(f"Packaging {name} as a debian from path {path}")

        # Copy installed files to the merged workspace (optinstall)
        shutil.copytree(
            path,
            self._optinstall,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(*IGNORE_PATTERNS)
        )

        # Create packaging folder structure
        staging_dir = Path("staging") / name

        # Clean old staging
        shutil.rmtree(staging_dir, ignore_errors=True)

        pkg_staging = (
            staging_dir
            / "opt"
            / self._graph.organization
            / self._graph.release_label
            / self._graph.distribution
        )
        pkg_staging.mkdir(parents=True)

        shutil.copytree(
            path,
            pkg_staging,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(*IGNORE_PATTERNS)
        )

        installed_size = calculate_size(str(staging_dir / "opt"))

        # Replace local paths with the correct /opt install location
        fix_local_paths(
            self._graph.organization,
            self._graph.release_label,
            self._graph.distribution,
            staging_dir, path
        )

        package = self._graph.packages[name]
        source_depends = []
        for dep in package.source_depends:
            dep_pkg = self._graph.packages[dep]
            source_depends.append(
                f"{dep_pkg.debian_name(*self._graph.debian_info)} (= {dep_pkg.debian_version(self._graph.build_date)})"
            )

        deb_name = package.debian_name(*self._graph.debian_info)
        deb_version = package.debian_version(self._graph.build_date)

        package_debian(
            deb_name,
            deb_version,
            package.description,
            package.maintainers,
            self._graph.os_version,
            staging_dir,
            source_depends + package.apt_depends,
            installed_size=installed_size
        )

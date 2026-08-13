import os
import shutil
import math
import time

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Event

from colcon_core.plugin_system import satisfies_version
from colcon_core.verb import VerbExtensionPoint
from colcon_core.verb.build import BuildVerb

from tailor_distro.blossom import Graph

from . import fix_local_paths, package_debian, environment_debian_info

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


class PackagingTaskWrapper:
    """Wraps a build task to submit debian packaging to a thread pool after a successful build."""

    def __init__(self, build_task, graph, ros_version, optinstall, packaging_executor, futures, packaging_failed):
        self._build_task = build_task
        self._graph = graph
        self._ros_version = ros_version
        self._optinstall = optinstall
        self._packaging_executor = packaging_executor
        self._futures = futures
        self._packaging_failed = packaging_failed

    def set_context(self, *, context):
        self._build_task.set_context(context=context)
        self._context = context
        self.context = context

    async def __call__(self, *args, **kwargs):
        # Check if a previous packaging job has failed — abort early
        if self._packaging_failed.is_set():
            print(f"Skipping build of {self._context.pkg.name}: a prior packaging job failed")
            return 1

        start = time.time()

        # Run the original build task
        rc = await self._build_task(*args, **kwargs)
        if rc:
            return rc

        duration = time.time() - start

        # Submit packaging to the thread pool — don't block the build
        name = self._context.pkg.name
        path = Path(self._context.args.install_base)

        self._futures.append(
            self._packaging_executor.submit(
                _package_debian_worker,
                name, path,
                self._graph, self._ros_version, self._optinstall,
                self._packaging_failed,
                duration
            )
        )

        return 0


def _package_debian_worker(name, path, graph, ros_version, optinstall, packaging_failed, build_time):
    """Runs in a background thread to package a single .deb."""
    try:
        _do_package_debian(name, path, graph, ros_version, optinstall, build_time)
    except Exception:
        print(f"Packaging FAILED for {name}")
        packaging_failed.set()
        raise


def _do_package_debian(name, path, graph, ros_version, optinstall, build_time):
    """Core packaging logic for a single .deb."""
    print(f"Packaging {name} as a debian from path {path}")

    # Copy installed files to the merged workspace (optinstall).
    # This is required as the non --merge-install build isolates
    # packages, which in turn requires 700+ individual paths to be
    # defined in the environment. By copying here we're effectively
    # merging all the packages after the fact, which allows us to
    # define a single path to the workspace
    # (ROS_PACKAGE_PATH/PYTHONPATH/LD_LIBRARY_PATH/etc)
    # Remove pre-existing files for this package from optinstall before merging
    # new artifacts in — avoids conflicts with files restored from restic.
    for dirpath, _, filenames in os.walk(str(path)):
        rel = os.path.relpath(dirpath, str(path))
        dst_dir = optinstall / rel if rel != "." else optinstall
        for name in filenames:
            (dst_dir / name).unlink(missing_ok=True)

    shutil.copytree(
        path,
        optinstall,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(*IGNORE_PATTERNS),
        symlinks=True,
    )

    # Create packaging folder structure
    staging_dir = Path("staging") / name

    # Clean old staging
    shutil.rmtree(staging_dir, ignore_errors=True)

    pkg_staging = (
        staging_dir
        / "opt"
        / graph.organization
        / graph.release_label
        / ros_version
    )
    pkg_staging.mkdir(parents=True)

    shutil.copytree(
        path,
        pkg_staging,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(*IGNORE_PATTERNS),
        symlinks=True
    )

    installed_size = calculate_size(str(staging_dir / "opt"))

    # Replace local paths with the correct /opt install location
    fix_local_paths(
        graph.organization,
        graph.release_label,
        ros_version,
        staging_dir, path
    )

    package = graph.packages[ros_version][name]

    # APT dependency names can be used as-is, but source dependencies
    # need to be converted to their debian equivalents with versions.
    build_depends = package.build_depends(types=["apt"])
    run_depends = package.run_depends(types=["apt"])

    for dep in package.build_depends(types=["source"]):
        dep_pkg = graph.packages[ros_version][dep]
        build_depends.append(
            f"{dep_pkg.debian_name(*graph.debian_info)} (= {dep_pkg.debian_version(graph.build_date)})"
        )

    for dep in package.run_depends(types=["source"]):
        dep_pkg = graph.packages[ros_version][dep]
        run_depends.append(
            f"{dep_pkg.debian_name(*graph.debian_info)} (= {dep_pkg.debian_version(graph.build_date)})"
        )

    # Always include the environment package as a dependency so
    # installing individual packages also installs the environment
    # scripts.
    run_depends.append(
        environment_debian_info(
            graph.organization,
            graph.package_name_release_label,
            ros_version,
            graph.build_date,
            graph.os_version
        )
    )

    # TODO: Ideally we would keep these separate but due to the need to build
    # overlays on target we really need to have all the build deps already
    # present in the workspace.
    if graph.merge_dependencies:
        run_depends.extend(build_depends)
        build_depends = []

    deb_name = package.debian_name(*graph.debian_info)
    deb_version = package.debian_version(graph.build_date)

    package_debian(
        deb_name,
        deb_version,
        package.description,
        package.maintainers,
        graph.os_version,
        staging_dir,
        build_depends=build_depends,
        run_depends=run_depends,
        installed_size=installed_size,
        build_time=build_time
    )


class DebianPackagerVerb(BuildVerb):
    """Extends the build verb to package debs inline as packages finish building."""

    def __init__(self):
        super().__init__()
        satisfies_version(VerbExtensionPoint.EXTENSION_POINT_VERSION, '^1.0')

    def add_arguments(self, *, parser):
        super().add_arguments(parser=parser)
        group = parser.add_argument_group(title='Debian packaging arguments')
        group.add_argument(
            '--graph', type=Path, required=True,
            help='Path to the packaging graph YAML file.'
        )
        group.add_argument(
            '--ros-version', required=True,
            help='The ROS distribution version to package.'
        )

    def main(self, *, context):
        args = context.args
        self._graph = Graph.from_yaml(args.graph)
        self._ros_version = args.ros_version

        # Set up merged optinstall directory
        optinstall_root = Path("optinstall")
        optinstall_root.mkdir(exist_ok=True)

        self._optinstall = (
            optinstall_root
            / self._graph.organization
            / self._graph.release_label
            / self._ros_version
        )
        self._optinstall.mkdir(parents=True, exist_ok=True)

        # Shared thread pool and futures list for background packaging
        self._packaging_executor = ThreadPoolExecutor(max_workers=PACKAGING_THREADS)
        self._futures = []
        self._packaging_failed = Event()

        # Run the full build (packaging submits to thread pool as packages complete)
        build_rc = super().main(context=context)

        # Wait for all packaging threads to finish and collect errors
        errors = []
        for f in as_completed(self._futures):
            try:
                f.result()
            except Exception as e:
                errors.append(e)

        self._packaging_executor.shutdown(wait=False)

        if errors:
            for e in errors:
                print(f"Packaging error: {e}")
            return 1

        return build_rc

    def _get_jobs(self, args, decorators, install_base):
        jobs, unselected = super()._get_jobs(args, decorators, install_base)

        # Wrap each build task to submit packaging to the thread pool on completion
        for job in jobs.values():
            job.task = PackagingTaskWrapper(
                job.task, self._graph, self._ros_version, self._optinstall,
                self._packaging_executor, self._futures, self._packaging_failed,
            )

        return jobs, unselected

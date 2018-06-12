#!/usr/bin/python3
import argparse
import jinja2
import pathlib
import re

from bloom.generators.debian.generator import format_depends
from bloom.generators.common import resolve_dependencies

from catkin_pkg.topological_order import topological_order


def get_depends(packages, depend_type):
    depends = set()
    for package in packages.values():
        depends |= set(getattr(package, depend_type))

    # Filter out any dependencies that are in the workspace (i.e. non-system, catkin, packages)
    filtered_depends = {depend for depend in depends if depend.name not in packages.keys()}
    return filtered_depends


def main():
    parser = argparse.ArgumentParser(description='Pull the contents of a ROS distribution to disk.')
    parser.add_argument('--workspace-dir', type=pathlib.Path)
    args = parser.parse_args()

    # Flavour
    bundle_name = "developer"
    os_name = 'ubuntu'
    os_version = 'xenial'
    top_packages = ''

    default_build_depends = [
        'build-essential',
        'cmake',
        'debhelper',
        'python-catkin-tools',
    ]

    cxx_flags = [
        '-DNDEBUG',
        '-O3',
        '-g',
    ]
    cxx_standard = 14

    ros_distro = "locus"
    # TODO(end)

    packages = {
        package[1].name: package[1] for package in topological_order(str(args.workspace_dir / 'src'))
    }

    build_depends = get_depends(packages, 'build_depends')
    run_depends = get_depends(packages, 'run_depends')

    resolved_depends = resolve_dependencies(
        build_depends | run_depends,
        os_name=os_name,
        os_version=os_version
    )

    resolved_build_depends = format_depends(build_depends, resolved_depends) + default_build_depends
    resolved_run_depends = format_depends(run_depends, resolved_depends)

    # TODO(pbovbel) supplement flavour with other stuff
    context = {
        'build_depends': sorted(resolved_build_depends),
        'run_depends': sorted(resolved_run_depends),
        # 'src_dir': args.src_dir,
        # 'debian_dir': args.debian_dir,

        # Flavour
        'distro': os_name,
        'codename': os_version,
        'bundle_name': bundle_name,
        'cxx_flags': cxx_flags,
        'cxx_standard': cxx_standard,
        'ros_distro': ros_distro,
        'top_packages': top_packages,
    }

    env = jinja2.Environment(
        loader=jinja2.PackageLoader('tailor_distro', 'bundle_templates'),
        undefined=jinja2.StrictUndefined
    )
    env.filters['regex_replace'] = lambda s, find, replace: re.sub(find, replace, s)
    env.filters['union'] = lambda left, right: list(set().union(left, right))

    for template_name in env.list_templates():
        output_path = args.workspace_dir / template_name

        output_path.parent.mkdir(parents=True, exist_ok=True)

        template = env.get_template(template_name)
        stream = template.stream(**context)
        stream.dump(str(output_path))


if __name__ == '__main__':
    main()

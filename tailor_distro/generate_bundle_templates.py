#!/usr/bin/python3
import jinja2
import pathlib
import re

from collections import namedtuple

from bloom.generators.debian.generator import format_depends
from bloom.generators.common import resolve_dependencies

from catkin_pkg.topological_order import topological_order


WorkspacePackage = namedtuple("WorkspacePackage", "path definition")


def get_depends(packages, depend_type):
    depends = set()
    for package in packages.values():
        depends |= set(getattr(package.definition, depend_type))

    filtered_depends = {depend for depend in depends if depend.name not in packages.keys()}
    return filtered_depends


def main():

    # TODO(pbovbel) make args
    workspace_path = pathlib.Path('workspace/src')
    bundle_name = "developer"
    os_name = 'ubuntu'
    os_version = 'xenial'
    cxx_flags = [
        '-DNDEBUG',
        '-O3',
        '-g',
    ]
    cxx_standard = 14

    DEFAULT_BUILD_DEPENDS = [
        'build-essential',
        'cmake',
        'debhelper',
        # 'python-catkin-tools',
    ]
    ros_distro = "locus"
    # TODO(end)

    packages = {
        package[1].name: WorkspacePackage(path=package[0], definition=package[1])
        for package in topological_order(str(workspace_path))
    }

    build_depends = get_depends(packages, 'build_depends')
    run_depends = get_depends(packages, 'run_depends')

    resolved_depends = resolve_dependencies(
        build_depends | run_depends,
        os_name=os_name,
        os_version=os_version
    )

    resolved_build_depends = format_depends(build_depends, resolved_depends) + DEFAULT_BUILD_DEPENDS
    resolved_run_depends = format_depends(run_depends, resolved_depends)

    context = {
        'distro': os_name,
        'codename': os_version,
        'bundle_name': bundle_name,
        'build_depends': sorted(resolved_build_depends),
        'run_depends': sorted(resolved_run_depends),
        'cxx_flags': cxx_flags,
        'cxx_standard': cxx_standard,
        'ros_distro': ros_distro,
    }

    env = jinja2.Environment(
        loader=jinja2.PackageLoader('tailor_distro', 'bundle_templates'),
        undefined=jinja2.StrictUndefined
    )
    env.filters['regex_replace'] = lambda s, find, replace: re.sub(find, replace, s)
    env.filters['union'] = lambda left, right: list(set().union(left, right))

    for template_name in env.list_templates():
        output_path = workspace_path / template_name

        output_path.parent.mkdir(parents=True, exist_ok=True)

        template = env.get_template(template_name)
        stream = template.stream(**context)
        stream.dump(str(output_path))


if __name__ == '__main__':
    main()

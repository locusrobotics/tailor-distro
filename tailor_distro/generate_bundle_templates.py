#!/usr/bin/python3
import jinja2
import pathlib
import re

from collections import namedtuple
# from rosdep2 import catkin_packages

from bloom.generators.debian.generator import format_depends
from bloom.generators.common import resolve_dependencies

from catkin_pkg.topological_order import topological_order


WorkspacePackage = namedtuple("WorkspacePackage", "path definition")

DEFAULT_BUILD_DEPENDS = [
    'build-essential',
    'cmake',
    'debhelper',
    'python-catkin-tools',
]


def get_depends(packages, depend_type):
    depends = set()
    for package in packages.values():
        depends |= set(getattr(package.definition, depend_type))

    filtered_depends = {depend for depend in depends if depend.name not in packages.keys()}
    return filtered_depends


def main():
    workspace_path = pathlib.Path('workspace/src')
    os_name = 'ubuntu'
    os_version = 'xenial'

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
        'bundle_name': 'developer',
        'build_depends': sorted(resolved_build_depends),
        'run_depends': sorted(resolved_run_depends),
    }

    env = jinja2.Environment(
        loader=jinja2.PackageLoader('tailor_distro', 'debian_templates'),
        undefined=jinja2.StrictUndefined
    )
    env.filters['regex_replace'] = lambda s, find, replace: re.sub(find, replace, s)

    for template_name in env.list_templates():
        output_path = workspace_path / template_name

        output_path.parent.mkdir(parents=True, exist_ok=True)

        template = env.get_template(template_name)
        stream = template.stream(**context)
        stream.dump(str(output_path))


if __name__ == '__main__':
    main()

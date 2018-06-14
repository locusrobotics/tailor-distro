#!/usr/bin/python3
import argparse
import jinja2
import pathlib
import re
import yaml

from bloom.generators.debian.generator import format_depends
from bloom.generators.common import resolve_dependencies

from catkin_pkg.topological_order import topological_order


def get_depends_type(packages, depend_type):
    """Get a dependency subtype (build_depends|run_depends) from a package set"""
    depends = set()
    for package in packages.values():
        depends |= set(getattr(package, depend_type))

    # Filter out any dependencies that are in the workspace (i.e. non-system, catkin, packages)
    filtered_depends = {depend for depend in depends if depend.name not in packages.keys()}
    return filtered_depends


def get_dependencies(packages, os_name, os_version):
    """Get resolved dependencies from a set of packages"""
    build_depends = get_depends_type(packages, 'build_depends')
    run_depends = get_depends_type(packages, 'run_depends')

    resolved_depends = resolve_dependencies(
        build_depends | run_depends,
        os_name=os_name,
        os_version=os_version
    )

    resolved_build_depends = format_depends(build_depends, resolved_depends)
    resolved_run_depends = format_depends(run_depends, resolved_depends)

    return resolved_build_depends, resolved_run_depends


def create_templates(context, output_dir):
    """Create templates for debian build"""
    env = jinja2.Environment(
        loader=jinja2.PackageLoader('tailor_distro', 'debian_templates'),
        undefined=jinja2.StrictUndefined
    )
    env.filters['regex_replace'] = lambda s, find, replace: re.sub(find, replace, s)
    env.filters['union'] = lambda left, right: list(set().union(left, right))

    for template_name in env.list_templates():
        output_path = output_dir / template_name

        output_path.parent.mkdir(parents=True, exist_ok=True)

        template = env.get_template(template_name)
        stream = template.stream(**context)
        stream.dump(str(output_path))


def main():
    parser = argparse.ArgumentParser(description='Pull the contents of a ROS distribution to disk.')
    parser.add_argument('--workspace-dir', type=pathlib.Path, required=True)
    parser.add_argument('--recipe', type=pathlib.Path, required=True)
    args = parser.parse_args()

    recipe = yaml.load(args.recipe.open())

    packages = {
        package[1].name: package[1] for package in topological_order(str(args.workspace_dir / 'src'))
    }

    build_depends, run_depends = get_dependencies(packages, recipe['os_name'], recipe['os_version'])

    build_depends += recipe['default_build_depends']

    debian_name = '-'.join([
        recipe['origin'],
        recipe['flavour'],
        recipe['release_label'],
    ])

    context = dict(
        build_depends=sorted(build_depends),
        run_depends=sorted(run_depends),
        debian_name=debian_name,
        **recipe
    )

    create_templates(context, args.workspace_dir)


if __name__ == '__main__':
    main()

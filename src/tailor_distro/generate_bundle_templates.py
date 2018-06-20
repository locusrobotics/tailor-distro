#!/usr/bin/python3
import argparse
import jinja2
import pathlib
import re
import yaml

from bloom.generators.debian.generator import format_depends
from bloom.generators.common import resolve_dependencies
from catkin_pkg.topological_order import topological_order


def get_dependencies(packages, depend_type, os_name, os_version):
    """Get resolved dependencies from a set of packages"""
    depends = set()
    for package in packages.values():
        depends |= set(getattr(package, depend_type))

    resolved_depends = resolve_dependencies(
        depends,
        peer_packages=packages.keys(),
        os_name=os_name,
        os_version=os_version,
        fallback_resolver=lambda key, peers: []
    )

    formatted_depends = format_depends(depends, resolved_depends)

    return formatted_depends


def create_templates(context, output_dir):
    """Create templates for debian build"""
    env = jinja2.Environment(
        loader=jinja2.PackageLoader('tailor_distro', 'debian_templates'),
        undefined=jinja2.StrictUndefined,
        trim_blocks=True
    )
    env.filters['regex_replace'] = lambda s, find, replace: re.sub(find, replace, s)
    env.filters['union'] = lambda left, right: list(set().union(left, right))

    for template_name in env.list_templates():
        output_path = output_dir / template_name

        output_path.parent.mkdir(parents=True, exist_ok=True)

        template = env.get_template(template_name)
        stream = template.stream(**context)
        stream.dump(str(output_path))


def get_packages_in_workspace(workspace, root_packages_list=[]):
    """Get a list of all packages in a workspace. Optionally filter to only include direct dependencies of a
    root package list.
    """
    if root_packages_list is None:
        return {}

    packages = {}

    # Load all packages and their descriptions (processed package.xml)
    for package in topological_order(str(workspace)):
        packages[package[1].name] = (package[1])

    if root_packages_list == []:
        return packages

    # Traverse the dependency tree starting with root_packages_list
    queued = set(root_packages_list)
    processed = set()
    filtered = set()

    while queued:
        package = queued.pop()
        processed.add(package)
        try:
            package_description = packages[package]
            filtered.add(package)
        except:
            continue

        for dependency in package_description.build_depends + package_description.run_depends:
            if dependency.name not in processed:
                queued.add(dependency.name)

    # Return the subset of packages found to be dependencies of root_package_list
    return {package: packages[package] for package in filtered}


def main():
    parser = argparse.ArgumentParser(description='Generate debian package templates from a recipe.')
    parser.add_argument('--src-dir', type=pathlib.Path, required=True)
    parser.add_argument('--template-dir', type=pathlib.Path, required=True)
    parser.add_argument('--recipe', type=pathlib.Path, required=True)
    args = parser.parse_args()

    recipe = yaml.load(args.recipe.open())

    build_depends = []
    run_depends = []

    for rosdistro in recipe['rosdistros']:
        packages = get_packages_in_workspace(args.src_dir / rosdistro, recipe['root_packages'][rosdistro])
        build_depends += get_dependencies(packages, 'build_depends', recipe['os_name'], recipe['os_version'])
        run_depends += get_dependencies(packages, 'run_depends', recipe['os_name'], recipe['os_version'])

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

    create_templates(context, args.template_dir)


if __name__ == '__main__':
    main()

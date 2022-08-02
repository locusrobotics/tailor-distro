#!/usr/bin/python3
import argparse
import click
import jinja2
import os
import pathlib
import re
import stat
import sys

from . import debian_templates, YamlLoadAction, SCHEME_S3

from typing import Iterable, List, Mapping, MutableMapping, MutableSet, Callable, Any, Tuple, Dict, Set

from bloom.generators.debian.generator import format_depends
from bloom.generators.common import resolve_dependencies
from catkin_pkg.topological_order import topological_order
from catkin_pkg.package import Package, Dependency


def get_debian_depends(package: Package):
    return {d for d in package.build_export_depends + package.buildtool_export_depends + package.exec_depends
            if d.evaluated_condition}


def get_debian_build_depends(package: Package):
    deps = package.build_depends + package.doc_depends + package.test_depends + package.buildtool_depends
    deps += package.build_export_depends + package.buildtool_export_depends
    return {d for d in deps if d.evaluated_condition}


def get_dependencies(packages: Mapping[str, Package], peer_packages: Set[str],
                     dependecy_getter: Callable[[Package], Iterable[Dependency]],
                     os_name: str, os_version: str) -> Iterable[str]:
    """Get resolved dependencies from a set of packages"""
    depends: MutableSet[Dependency] = set()
    resolved_depends: MutableMapping[Dependency, Tuple[str, str, str]] = {}
    for package in packages.values():
        click.echo(f"Gathering dependencies for package {package.name} ...", err=True)
        new_depends = set(dependecy_getter(package)) - depends
        if new_depends:
            click.echo("Resolving {} ...".format(', '.join(map(lambda d: d.name, new_depends))), err=True)
            depends |= new_depends
            resolved_depends.update(resolve_dependencies(
                new_depends,
                peer_packages=peer_packages,
                os_name=os_name,
                os_version=os_version,
                fallback_resolver=lambda key, peers: []
            ))

    formatted_depends = format_depends(depends, resolved_depends)

    return formatted_depends


TEMPLATE_SUFFIX = '.j2'


def create_templates(context: Mapping[str, str], output_dir: pathlib.Path) -> None:
    """Create templates for debian build"""
    env = jinja2.Environment(
        loader=jinja2.PackageLoader('tailor_distro', 'debian_templates'),
        undefined=jinja2.StrictUndefined,
        trim_blocks=True
    )
    env.filters['regex_replace'] = lambda s, find, replace: re.sub(find, replace, s)
    env.filters['union'] = lambda left, right: list(set().union(left, right))

    for template_name in env.list_templates():
        if not template_name.endswith(TEMPLATE_SUFFIX):
            continue
        template_path = pathlib.Path(debian_templates.__file__).parent / template_name
        output_path = output_dir / template_name[:-len(TEMPLATE_SUFFIX)]

        output_path.parent.mkdir(parents=True, exist_ok=True)

        template = env.get_template(template_name)
        stream = template.stream(**context)
        click.echo(f"Writing {output_path} ...", err=True)
        stream.dump(str(output_path))

        current_permissions = stat.S_IMODE(os.lstat(template_path).st_mode)
        os.chmod(output_path, current_permissions)


def get_packages_in_workspace(workspace: pathlib.Path, root_packages: Iterable[str] = []) -> Mapping[str, Package]:
    """Get a list of all packages in a workspace. Optionally filter to only include direct dependencies of a
    root package list.
    """
    if root_packages is None:
        return {}

    packages = {}

    # Load all packages and their descriptions (processed package.xml)
    for package in topological_order(str(workspace)):
        packages[package[1].name] = (package[1])

    if root_packages == []:
        return packages

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
        except Exception:
            continue

        for dependency in get_debian_depends(package_description) | get_debian_build_depends(package_description):
            if dependency.name not in processed:
                queued.add(dependency.name)

    # Return the subset of packages found to be dependencies of root_package_list
    return {package: packages[package] for package in filtered}


def generate_bundle_template(recipe: Mapping[str, Any], src_dir: pathlib.Path, template_dir: pathlib.Path) -> None:
    """Generate templates for debian packaging using a set of source packages, and recipe definition.
    :param recipe: Recipe definition, specifying which packages to build and how.
    :param src_dir: Location of package sources for dependency extraction.
    :param template_dir: Path where templates should be generated.
    """
    build_depends: List[str] = []
    run_depends: List[str] = []
    peer_packages: Dict[str, Set[str]] = {}

    for distro_name, distro_options in recipe['distributions'].items():
        click.echo(f"Building templates for rosdistro {distro_name} ...", err=True)
        packages = get_packages_in_workspace(src_dir / distro_name, distro_options.get('root_packages', None))
        peer_packages[distro_name] = packages

        for underlay in distro_options['underlays']:
            peer_packages[distro_name] |= peer_packages[underlay]

        build_depends += get_dependencies(
            packages, peer_packages[distro_name], get_debian_build_depends, recipe['os_name'],
            recipe['os_version']
        )
        run_depends += get_dependencies(
            packages, peer_packages[distro_name], get_debian_depends, recipe['os_name'], recipe['os_version'])

    build_depends += recipe['default_build_depends']

    debian_name = '-'.join([
        recipe['organization'],
        recipe['flavour'],
        recipe['release_label'],
    ])

    recipe['python_version'] = os.environ['ROS_PYTHON_VERSION']

    assert(recipe['apt_repo'].startswith(SCHEME_S3))
    context = dict(
        build_depends=sorted(build_depends),
        run_depends=sorted(run_depends),
        debian_name=debian_name,
        bucket_name=recipe['apt_repo'][len(SCHEME_S3):],
        **recipe
    )

    create_templates(context, template_dir)


def main():
    parser = argparse.ArgumentParser(description=generate_bundle_template.__doc__)
    parser.add_argument('--recipe', action=YamlLoadAction, required=True)
    parser.add_argument('--src-dir', type=pathlib.Path, required=True)
    parser.add_argument('--template-dir', type=pathlib.Path, required=True)
    args = parser.parse_args()

    sys.exit(generate_bundle_template(**vars(args)))


if __name__ == '__main__':
    main()

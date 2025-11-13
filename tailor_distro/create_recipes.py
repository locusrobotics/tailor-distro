#!/usr/bin/python3
import argparse
import click
import collections
import pathlib
import sys
import yaml

from copy import deepcopy

from typing import Mapping, Any

from . import YamlLoadAction


def nested_update(d, u):
    d = deepcopy(d)
    for k, v in u.items():
        if isinstance(v, collections.abc.Mapping):
            d[k] = nested_update(d.get(k, {}), v)
        else:
            d[k] = v
    return d


def check_distro(recipe, os_version):
    tmp = deepcopy(recipe)
    for distro, config in recipe["distributions"].items():
        os_list = config.get("os", [])
        if len(os_list) != 0:
            if os_version not in os_list:
                del tmp["distributions"][distro]
    return tmp


def create_recipes(recipes: Mapping[str, Any], recipes_dir: pathlib.Path, release_track: str,
                   release_label: str, debian_version: str) -> None:
    """Create individual recipe defintions from a master recipes configuration.
    :param recipes: Recipe configuration.
    :param recipes_dir: Path where to write individual recipe definitions.
    :param release_track: Release track to use.
    :param release_label: Parent label of all recipes.
    :param debian_version: Version of debian package.
    """
    output_recipes = {}
    for os_name, os_versions in recipes['os'].items():
        for os_version in os_versions:
            common_label = "-".join(["common", os_version, release_label])
            common_path = (recipes_dir / (common_label + ".yaml"))
            common_path.parent.mkdir(parents=True, exist_ok=True)

            common_recipe = dict(
                **recipes["common"],
                flavour="common",
                os_name=os_name,
                os_version=os_version,
                build_date=debian_version,
            )

            click.echo(f"Writing {common_path} ...", err=True)

            common_path.write_text(yaml.dump(common_recipe))
            output_recipes[common_label] = str(common_path)

            for flavour, recipe_options in recipes['flavours'].items():
                recipe_label = '-'.join([flavour, os_version, release_label])
                recipe_path = (recipes_dir / (recipe_label + '.yaml'))
                recipe_path.parent.mkdir(parents=True, exist_ok=True)

                recipe = check_distro(recipe_options, os_version)

                recipe = dict(
                    **recipe_options,
                    flavour=flavour,
                    os_name=os_name,
                    os_version=os_version,
                    path=str(recipe_path),
                    release_track=release_track,
                    release_label=release_label,
                )
                click.echo(f"Writing {recipe_path} ...", err=True)
                recipe_path.write_text(yaml.dump(recipe))
                output_recipes[recipe_label] = str(recipe_path)

    print(yaml.dump(output_recipes))


def main():
    parser = argparse.ArgumentParser(description=create_recipes.__doc__)
    parser.add_argument('--recipes', action=YamlLoadAction, required=True)
    parser.add_argument('--recipes-dir', type=pathlib.Path, required=True)
    parser.add_argument('--release-track', type=str, required=True)
    parser.add_argument('--release-label', type=str, required=True)
    parser.add_argument('--debian-version', type=str, required=True)
    args = parser.parse_args()

    sys.exit(create_recipes(**vars(args)))


if __name__ == '__main__':
    main()

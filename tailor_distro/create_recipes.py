#!/usr/bin/python3
import argparse
import pathlib
import yaml


def main():
    parser = argparse.ArgumentParser(description='Pull the contents of a ROS distribution to disk.')
    parser.add_argument('--recipes', type=pathlib.Path, required=True)
    parser.add_argument('--recipes-dir', type=pathlib.Path, required=True)
    parser.add_argument('--series', type=str, required=True)
    parser.add_argument('--version', type=str, required=True)
    args = parser.parse_args()

    recipes = yaml.load(args.recipes.open())

    recipe_list = {}
    for os_name, os_versions in recipes['os'].items():
        for os_version in os_versions:
            for flavour, options in recipes['flavours'].items():
                label = '-'.join([flavour, os_name, os_version, args.series])
                recipe_path = (args.recipes_dir / label / 'recipe.yaml')
                recipe_path.parent.mkdir(parents=True, exist_ok=True)
                recipe = dict(
                    flavour=flavour,
                    os_name=os_name,
                    os_version=os_version,
                    path=str(recipe_path),
                    series=args.series,
                    package_version=args.version,
                    **recipes['common'],
                    **options,
                )
                recipe_path.write_text(yaml.dump(recipe))
                recipe_list[label] = str(recipe_path)

    print(yaml.dump(recipe_list))


if __name__ == '__main__':
    main()

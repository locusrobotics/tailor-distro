#!/usr/bin/python3
import argparse
import pathlib
import yaml


def main():
    parser = argparse.ArgumentParser(description='Pull the contents of a ROS distribution to disk.')
    parser.add_argument('--recipes', type=pathlib.Path, required=True)
    parser.add_argument('--recipes-dir', type=pathlib.Path, required=True)
    parser.add_argument('--release-label', type=str, required=True)
    parser.add_argument('--package-version', type=str, required=True)
    args = parser.parse_args()

    recipes = yaml.load(args.recipes.open())

    recipe_list = {}
    for os_name, os_versions in recipes['os'].items():
        for os_version in os_versions:
            for flavour, options in recipes['flavours'].items():
                recipe_label = '-'.join([flavour, os_name, os_version, args.release_label])
                recipe_path = (args.recipes_dir / recipe_label / 'recipe.yaml')
                recipe_path.parent.mkdir(parents=True, exist_ok=True)
                recipe = dict(
                    flavour=flavour,
                    os_name=os_name,
                    os_version=os_version,
                    path=str(recipe_path),
                    release_label=args.release_label,
                    package_version=args.package_version,
                    **recipes['common'],
                    **options,
                )
                recipe_path.write_text(yaml.dump(recipe))
                recipe_list[recipe_label] = str(recipe_path)

    print(yaml.dump(recipe_list))


if __name__ == '__main__':
    main()

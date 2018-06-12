#!/usr/bin/python3
import argparse
import pathlib


def main():
    parser = argparse.ArgumentParser(description='Pull the contents of a ROS distribution to disk.')
    parser.add_argument('--flavours-config', type=pathlib.Path)
    parser.add_argument('--flavour-dir', type=pathlib.Path)
    args = parser.parse_args()

    flavours = yaml.load(args.flavours_config.open())
    print(flavours)


if __name__ == '__main__':
    main()

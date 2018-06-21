import argparse
import pathlib
import yaml

__version__ = '0.0.0'


class YamlLoadAction(argparse.Action):
    def __init__(self, option_strings, dest, nargs=None, **kwargs):
        if nargs is not None:
            raise ValueError("Only supports a single arg, nargs not allowed")
        super(YamlLoadAction, self).__init__(option_strings, dest, **kwargs)

    def __call__(self, parser, namespace, value, option_string=None):
        setattr(namespace, self.dest, yaml.safe_load(pathlib.Path(value).open()))

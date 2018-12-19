__version__ = '0.0.0'

import argparse
import json
import pathlib
import subprocess
import sys
import yaml


SCHEME_S3 = "s3://"


class YamlLoadAction(argparse.Action):
    def __init__(self, option_strings, dest, nargs=None, **kwargs):
        if nargs is not None:
            raise ValueError("Only supports a single arg, nargs not allowed")
        super(YamlLoadAction, self).__init__(option_strings, dest, **kwargs)

    def __call__(self, parser, namespace, value, option_string=None):
        setattr(namespace, self.dest, yaml.safe_load(pathlib.Path(value).open()))


def aptly_configure(apt_repo, release_track):
    assert(apt_repo.startswith(SCHEME_S3))
    bucket_name = apt_repo.strip(SCHEME_S3)
    aptly_endpoint = f"s3:{bucket_name}:{release_track}/ubuntu/"

    aptly_config = {
        "rootDir": "/aptly",
        "gpgProvider": "internal",
        "dependencyFollowSuggests": True,
        "dependencyFollowRecommends": True,
        "dependencyFollowAllVariants": True,
        "S3PublishEndpoints": {
                bucket_name: {
                    "region": "us-east-1",
                    "bucket": bucket_name,
                    "acl": "private",
                    "debug": False
                }
        }
    }

    with open(pathlib.Path.home() / ".aptly.conf", mode='w') as aptly_config_file:
        json.dump(aptly_config, aptly_config_file)

    return aptly_endpoint


def run_command(cmd):
    print(' '.join(cmd), file=sys.stderr)
    subprocess.run(cmd, check=True)

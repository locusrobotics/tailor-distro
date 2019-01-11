#!/usr/bin/python3
import abc
import pathlib
import yaml

from rosdistro import get_index, get_distribution
from rosdistro.writer import yaml_from_distribution_file


class BaseVerb(metaclass=abc.ABCMeta):
    """Abstract base class for all distro management verbs."""

    @abc.abstractmethod
    def execute(self, rosdistro_path, distro):
        self.rosdistro_path = rosdistro_path
        internal_index_path = (rosdistro_path / 'rosdistro' / 'index.yaml').resolve().as_uri()
        self.internal_index = get_index(internal_index_path)
        self.internal_distro = get_distribution(self.internal_index, distro)
        self.internal_distro_file = self.internal_index.distributions[distro]['distribution'][-1]

    def register_arguments(self, parser):
        parser.set_defaults(verb=self.execute)
        parser.add_argument('--distro', required=True, help="Distribution on which to operate")
        # TODO(pbovbel) Use path relative to package?
        parser.add_argument('--rosdistro-path', type=pathlib.Path, default='.', help="Index URL override")

    def repositories_arg(self, parser):
        parser.add_argument('repositories', nargs='*', metavar='REPO', help="Repositories to operate on")

    def upstream_arg(self, parser):
        parser.add_argument('--upstream-distro', help="Upstream distribution override")
        parser.add_argument('--upstream-index', help="Upstream index URL override")

    def load_upstream(self, distro, upstream_index, upstream_distro):
        recipes = yaml.safe_load((self.rosdistro_path / 'config' / 'recipes.yaml').open())
        try:
            info = recipes['common']['distributions'][distro]['upstream']
        except KeyError:
            info = None
        index = get_index(upstream_index if upstream_index is not None else info['url'])
        self.upstream_distro = get_distribution(
            index,
            upstream_distro if upstream_distro is not None else info['name']
        )

    def write_internal_distro(self):
        distro_file_path = pathlib.Path(self.internal_distro_file[len('file://'):])
        distro_file_path.write_text(yaml_from_distribution_file(self.internal_distro))

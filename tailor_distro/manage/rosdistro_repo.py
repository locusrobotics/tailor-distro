import abc
import click
import difflib
import git
import pathlib
import re
from rosdistro import get_index, get_distribution, Index
from rosdistro.distribution_file import create_distribution_file
from rosdistro.writer import yaml_from_distribution_file
from urllib.error import HTTPError
import yaml

from .base import get_github_client


GITHUB_PATTERN = re.compile('https?://github.com/(?P<org>[^/]+)/(?P<repo>.+)\.git')
GITHUB_BRANCH_PATTERN = re.compile('https://github.com/(?P<org>[^/]+)/(?P<repo>[^/]+)/tree/(?P<branch>.*)')
RAW_GITHUB_PATTERN = re.compile(r'https://raw.githubusercontent.com/'
                                r'(?P<repo>[^/]+/[^/]+)/(?P<branch>.+)/(?P<path>rosdistro/.+)')
REPO_URL_PATTERNS = [GITHUB_PATTERN, GITHUB_BRANCH_PATTERN, RAW_GITHUB_PATTERN]


def parse_repo_url(url):
    for pattern in REPO_URL_PATTERNS:
        m = pattern.match(url)
        if m:
            return m.groupdict()


class RepositoryBase(metaclass=abc.ABCMeta):
    """
        Abstract class for operating on a rosdistro repository.
        Implementing classes should set
         * self.internal_index (rosdistro.Index)
         * self.interal_distro (rosdistro.Distribution)
         * self.internal_distro_path (relative path to distro file)
         * self.distro_name (string name of distro)
        (and implement the abstract methods)
    """

    @abc.abstractmethod
    def read_file(self, path):
        """ Read the specified relative path and return the contents """

    @abc.abstractmethod
    def write_file(self, path, new_contents, message=None):
        """ Write the new contents to the given relative path. Optional message describes the change """

    def read_yaml_file(self, path):
        """ Read the specified relative path, and return the contents parsed as a yaml file """
        return yaml.safe_load(self.read_file(path))

    @abc.abstractmethod
    def get_branch_name(self):
        """ Return a string of the branch name we're operating on """

    def __getitem__(self, key):
        """ Return the repositories entry corresponding with key """
        return self.internal_distro.repositories.get(key)

    def get_repo_names(self):
        return set(self.internal_distro.repositories.keys())

    def get_upstream_distro(self, upstream_index, upstream_distro):
        recipes = self.read_yaml_file('config/recipes.yaml')
        try:
            info = recipes['common']['distributions'][self.distro_name]['upstream']
        except KeyError:
            info = None

        index = get_index(upstream_index if upstream_index is not None else info['url'])
        return get_distribution(index, upstream_distro if upstream_distro is not None else info['name'])

    def write_internal_distro(self, message=None):
        new_contents = yaml_from_distribution_file(self.internal_distro)
        self.write_file(self.internal_distro_path, new_contents, message)


class LocalROSDistro(RepositoryBase):
    def __init__(self, rosdistro_path, distro_name):
        self.rosdistro_path = pathlib.Path(rosdistro_path)
        self.distro_name = distro_name
        internal_index_path = (self.rosdistro_path / 'rosdistro' / 'index.yaml').resolve()

        if not internal_index_path.exists():
            raise FileNotFoundError(f'No such file: {internal_index_path}')

        self.internal_index = get_index(internal_index_path.as_uri())
        self.internal_distro = get_distribution(self.internal_index, distro_name)

        self.internal_distro_path = self.internal_index.distributions[distro_name]['distribution'][-1][len('file://'):]

    def read_file(self, path):
        path_obj = self.rosdistro_path / path
        with path_obj.open() as f:
            return f.read()

    def write_file(self, path, new_contents, message=None):
        path_obj = pathlib.Path(path)
        path_obj.write_text(new_contents)

    def get_branch_name(self):
        rosdistro_repo = git.Repo(self.rosdistro_path)
        return str(rosdistro_repo.active_branch)


def get_distro_from_index(index, dist_name, type_='distribution'):
    """
       Portion of the logic from rosdistro.get_distribution
    """
    if dist_name not in index.distributions.keys():
        valid_names = ', '.join(sorted(index.distributions.keys()))
        raise RuntimeError("Unknown release: '{0}'. Valid release names are: {1}".format(dist_name, valid_names))
    dist = index.distributions[dist_name]
    if type_ not in dist.keys():
        raise RuntimeError('unknown release type "%s"' % type_)

    return dist[type_]


class RemoteROSDistro(RepositoryBase):
    def __init__(self, rosdistro_url, rosdistro_branch, distro_name):
        repo_info = parse_repo_url(rosdistro_url)

        if not repo_info:
            raise RuntimeError(f'Cannot parse rosdistro_url {rosdistro_url}')

        gh = get_github_client()
        self.repo = gh.get_repo(repo_info['repo'])
        self.path = repo_info['path']
        self.branch = rosdistro_branch or repo_info['branch']

        try:
            self.internal_index = get_index(rosdistro_url)
            self.internal_distro = get_distribution(self.internal_index, distro_name)
        except HTTPError:
            # Only needed for private github repositories
            distro_folder = pathlib.Path(self.path).parent
            self.internal_index = Index(self.read_yaml_file(self.path), str(distro_folder))

            dist_url = get_distro_from_index(self.internal_index, distro_name)
            if not isinstance(dist_url, list):
                data = self.read_yaml_file(dist_url)
            else:
                data = []
                for u in dist_url:
                    data.append(self.read_yaml_file(str(u)))
            self.internal_distro = create_distribution_file(distro_name, data)

        self.internal_distro_path = self.internal_index.distributions[distro_name]['distribution'][-1]

    def read_file(self, path):
        git_file = self.repo.get_contents(path, self.branch)
        return git_file.decoded_content.decode()

    def write_file(self, path, new_contents, message=None, make_confirmation=True):
        git_file = self.repo.get_contents(path, self.branch)
        if make_confirmation:
            original_contents = git_file.decoded_content.decode()
            for i, line in enumerate(difflib.unified_diff(original_contents.split('\n'), new_contents.split('\n'),
                                                          lineterm='', fromfile=path, tofile='%s (modified)' % path)):
                if i < 2:
                    click.echo(click.style(line, bold=True), err=True)
                elif line and line[0] == '@':
                    click.echo(click.style(line, fg='cyan'), err=True)
                elif line and line[0] == '+':
                    click.echo(click.style(line, fg='green'), err=True)
                elif line and line[0] == '-':
                    click.echo(click.style(line, fg='red'), err=True)
                else:
                    click.echo(line, err=True)

            if message:
                confirm_text = f'Make commit "{message}"?'
            else:
                confirm_text = 'Make commit?'

            try:
                response = click.confirm(confirm_text, err=True)
            except click.Abort:
                response = False

            if not response:
                click.echo('Maybe later', err=True)
                return

        if message is None:
            try:
                message = click.prompt('Enter commit message', err=True)
            except click.Abort:
                click.echo('Aborting...', err=True)
                return

        self.repo.update_file(path, message, new_contents, git_file.sha, branch=self.branch)

    def get_branch_name(self):
        return self.branch

#!/usr/bin/python3
import click
from github import GithubException
from .base import BaseVerb, get_github_client
from .rosdistro_repo import parse_repo_url


def get_tag(repo, tag_name):
    for tag in repo.get_tags():
        if tag.name == tag_name:
            return tag


def get_chain(parent, child, limit=5):
    for i in range(limit):
        yield child
        if len(child.parents) == 1:
            child = child.parents[0]
            if child == parent:
                break


def get_status(gh, repo_entry, release_branch, ignore_committer=None):
    try:
        release_tag = repo_entry.release_repository.version

        repo_dict = parse_repo_url(repo_entry.release_repository.url)
        repo = gh.get_repo(repo_dict['repo'])
        tag_commit = get_tag(repo, release_tag).commit.commit
        branch_commit = repo.get_branch(release_branch).commit.commit

        if tag_commit == branch_commit:
            return release_tag, '', 'green'

        commits_behind = 0
        for commit in get_chain(tag_commit, branch_commit):
            if not ignore_committer or commit.committer.name != ignore_committer:
                commits_behind += 1

        if commits_behind == 0:
            return release_tag, '*', 'green'
        elif commits_behind == 1:
            return release_tag, f'{commits_behind} commit behind', 'yellow'
        else:
            return release_tag, f'{commits_behind} commits behind', 'yellow'
    except GithubException as e:
        return '', e.data['message'], 'red'


class QueryReleaseVerb(BaseVerb):
    name = 'query_release'

    def register_arguments(self, parser):
        super().register_arguments(parser)
        self.filter_args(parser)
        parser.add_argument('--ignore-committer')

    def execute(self, rosdistro_repo, name_pattern, url_pattern, ignore_committer):
        super().execute(rosdistro_repo)
        gh = get_github_client()

        for repo_name in sorted(rosdistro_repo.get_repo_names(name_pattern, url_pattern)):
            tag, message, color = get_status(gh, rosdistro_repo[repo_name], rosdistro_repo.branch, ignore_committer)
            click.echo(click.style(f'{repo_name:>20} {tag:>10} {message}', fg=color))

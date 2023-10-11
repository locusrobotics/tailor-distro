#!/usr/bin/python3
import click
import git
import re
import subprocess
import tempfile

from rosdistro.release_repository_specification import ReleaseRepositorySpecification

from .base import BaseVerb, insert_auth_token, get_github_token
from .. import run_command

version_regexp = re.compile(r'^[0-9]+\.[0-9]+$')


class ReleaseVerb(BaseVerb):
    """Cut a bulk release of all specified repositories. """
    name = 'release'

    def register_arguments(self, parser):
        super().register_arguments(parser)
        self.repositories_arg(parser)
        parser.add_argument('--release-version', required=True, type=str, help="Release version (e.g. '22')")
        parser.add_argument('--dry-run', action='store_true', default=False, help="Do not actually permorm the action")

    def execute(self, rosdistro_repo, repositories, release_version, dry_run):
        super().execute(rosdistro_repo)

        release_branch_name = f'release/{release_version}'

        if self.rosdistro_repo.get_branch_name() != release_branch_name:
            click.echo(click.style(f"rosdistro should be on '{release_branch_name}' branch", fg='red'), err=True)
            return 1

        github_token = get_github_token()

        # If list of repositories is a single item with a string for all repos, convert to a proper list
        if len(repositories) == 1:
            repositories = repositories[0].split()
        print(repositories)

        for name in repositories:
            click.echo(click.style(f"---\nReleasing repository '{name}'", fg='green'), err=True)
            data = self.rosdistro_repo[name]
            repo_url = data.source_repository.url
            source_version = data.source_repository.version

            with tempfile.TemporaryDirectory() as temp_dir:
                click.echo(click.style(f'Cloning {repo_url} into {temp_dir}', fg='green'), err=True)
                clone_url = insert_auth_token(url=repo_url, token=github_token)

                repo = git.Repo.clone_from(clone_url, temp_dir)
                origin = repo.remotes.origin

                # Check for release branch on remote
                try:
                    click.echo(click.style(f"Checkout release branch '{release_branch_name}'...", fg='green'), err=True)
                    remote_release_branch = origin.refs[release_branch_name]
                    release_branch = repo.create_head(release_branch_name, commit=remote_release_branch)
                    release_branch.checkout()
                    new_release = False
                except IndexError:
                    new_release = True
                    if source_version == release_branch_name:
                        click.echo(click.style(f"Branch '{release_branch_name}' does not exist, but is listed in the "
                                               "distribution, aborting.", fg='red'), err=True)
                        return 1

                    click.echo(click.style(f"Release branch '{release_branch_name}' does not exist, this is a new "
                                           "release", fg='green'), err=True)

                repo.create_head(source_version, origin.refs[source_version])
                repo.heads[source_version].checkout()

                if new_release:
                    latest_tag = None

                    self._generate_changelogs_prepare_release(repo, latest_tag, temp_dir)

                    click.echo(click.style(f"Pushing source branch '{source_version}'...", fg='green'), err=True)
                    if not dry_run:
                        origin.push(source_version)

                    click.echo(click.style(f"Creating release branch '{release_branch_name}' from "
                                           f"'{source_version}'...", fg='green'), err=True)
                    release_branch = repo.create_head(release_branch_name, commit=origin.refs[source_version])

                    latest_tag = self._get_current_tag(repo, release_version)

                else:
                    latest_tag = self._get_current_tag(repo, release_version)
                    if latest_tag:
                        click.echo(click.style(f"HEAD of {release_branch} has been released as {latest_tag} before, "
                                               "skipping.", fg='yellow'), err=True)
                        self._update_rosdistro_entry(name, latest_tag, release_branch_name, new_release)
                        continue

                    self._generate_changelogs_prepare_release(repo, latest_tag, temp_dir)

                if not dry_run:
                    click.echo(click.style(f"Pushing release branch '{release_branch_name}'...", fg='green'), err=True)
                    origin.push(release_branch)

                    if latest_tag:
                        click.echo(
                            click.style(f"Pushing latest tag '{latest_tag}'...", fg='green'),
                            err=True
                        )
                        origin.push(latest_tag)

                self._update_rosdistro_entry(name, latest_tag, release_branch_name, new_release)

    def _update_rosdistro_entry(self, name, latest_tag, release_branch_name, new_release):
        if new_release:
            msg = f"Updating rosdistro with release of '{name}' as version {latest_tag}"
        else:
            msg = f"Updating rosdistro with release branch of '{name}' as {release_branch_name}"

        click.echo(click.style(msg, fg='yellow'), err=True)
        data = self.rosdistro_repo[name]
        data.source_repository.version = release_branch_name
        if data.release_repository is None and latest_tag and not new_release:
            data.release_repository = ReleaseRepositorySpecification(
                name, {'version': latest_tag, 'url': data.source_repository.url, 'tags': {'release': '{{ version }}'}}
            )
        elif latest_tag and not new_release:
            data.release_repository.version = latest_tag

        self.rosdistro_repo.write_internal_distro(msg)

    def _get_current_tag(self, repo, release_version):
        click.echo(click.style(f"Checking for a tag to have been created...", fg='green'), err=True)
        current_tags = [
            tag for tag in repo.tags if
            tag.commit == repo.head.commit
        ]
        if len(current_tags) > 1:
            raise RuntimeError("More than one tag on HEAD of repository, ambiguous")
        try:
            latest_tag = str(current_tags[0])
        except IndexError:
            latest_tag = None

        click.echo(click.style(f"Found {latest_tag}", fg='green'), err=True)
        return latest_tag

    def _generate_changelogs_prepare_release(self, repo, latest_tag, temp_dir):
        """Generate changelogs and run catkin_prepare_release."""
        click.echo(click.style("Generating changelogs...", fg='green'), err=True)
        changelog_command = ['catkin_generate_changelog', '--skip-merges', '-y']

        try:
            run_command(changelog_command, cwd=temp_dir, capture_output=True)
        except subprocess.CalledProcessError as e:
            if "Could not fetch latest tag" in e.stderr.decode():
                run_command(changelog_command + ['--all'], cwd=temp_dir)
            else:
                # Need to print stdout/stderr, otherwise they get swallowed
                click.echo(e.stdout)
                click.echo(e.stderr, err=True)
                raise

        repo.index.add(['*'])
        repo.index.commit("Update changelogs")

        click.echo(click.style("Preparing release...", fg='green'), err=True)
        run_command(['catkin_prepare_release', '-y', '--no-color', '--no-push', '--bump',
                     'minor' if not latest_tag else 'patch'], cwd=temp_dir)

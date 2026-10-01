import json
import os
import subprocess
import sys

import pytest
import yaml
from catkin_pkg.packages import find_packages

from tailor_distro.pull_distro_repositories import (
    IGNORE_CONTENT,
    checkout_url,
    child_directory,
    filter_packages,
    github_authentication,
    pull_distro_repositories,
)


def git(path, *args):
    return subprocess.run(
        ["git", "-C", str(path), *args], check=True, capture_output=True, text=True,
    ).stdout.strip()


def package(path, name):
    path.mkdir(parents=True, exist_ok=True)
    (path / "package.xml").write_text(
        f'<package format="2"><name>{name}</name><version>1.0.0</version>'
        '<description>Test package</description>'
        '<maintainer email="test@example.com">Test</maintainer><license>BSD</license>'
        '</package>'
    )


@pytest.fixture
def source_repo(tmp_path):
    repo = tmp_path / "upstream"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.com")
    package(repo / "keep", "keep")
    package(repo / "exclude", "exclude")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "First")
    first = git(repo, "rev-parse", "HEAD")
    git(repo, "tag", "-a", "release/lyrical/tagged/1.0.0", "-m", "Release")
    (repo / "README").write_text("Second revision\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "Second")
    return repo, first


@pytest.fixture
def configuration(tmp_path, source_repo):
    repo, sha = source_repo
    source = {"type": "git", "url": repo.as_uri(), "version": "main"}
    repositories = {
        "branch": {"source": source},
        "tagged": {
            "source": dict(source, url=(tmp_path / "wrong-source").as_uri()),
            "release": {
                "url": repo.as_uri(),
                "version": "1.0.0",
                "tags": {"release": "release/{{ upstream }}/{{ package }}/{{ version }}"},
                "packages": ["keep"],
            },
        },
        "pinned": {
            "source": source,
            "release": {"url": repo.as_uri(), "version": sha, "tags": {"release": "{{ version }}"}},
        },
    }
    distributions = {}
    for name in ("ros1", "ros2"):
        (tmp_path / f"{name}.yaml").write_text(yaml.safe_dump({
            "type": "distribution", "version": 2, "repositories": repositories,
        }))
        distributions[name] = {"distribution": [f"{name}.yaml"]}
    index = tmp_path / "index.yaml"
    index.write_text(yaml.safe_dump({"type": "index", "version": 3, "distributions": distributions}))
    recipes = {"common": {"distributions": {
        name: {"upstream": {"name": "lyrical"}} for name in distributions
    }}}
    return index, recipes


def test_cli_shallow_clones_and_metadata(tmp_path, source_repo, configuration):
    upstream, first = source_repo
    index, recipes = configuration
    recipe_path = tmp_path / "recipes.yaml"
    recipe_path.write_text(yaml.safe_dump(recipes))
    src = tmp_path / "src"
    subprocess.run([
        sys.executable, "-m", "tailor_distro.pull_distro_repositories",
        "--src-dir", str(src), "--rosdistro-index", str(index),
        "--recipes", str(recipe_path), "--clean",
    ], check=True)
    for distro in ("ros1", "ros2"):
        root = src / distro
        expected = {"branch": git(upstream, "rev-parse", "HEAD"), "tagged": first, "pinned": first}
        records = [json.loads(line) for line in (root / f"{distro}_repositories_data.jsonl").read_text().splitlines()]
        assert {r["repo"]: r["sha"] for r in records} == expected
        for name, sha in expected.items():
            path = root / name
            assert git(path, "rev-parse", "HEAD") == sha
            assert git(path, "rev-parse", "--is-shallow-repository") == "true"
            assert git(path, "rev-list", "--count", "HEAD") == "1"
            assert next(r["path"] for r in records if r["repo"] == name) == str(path)
        assert (root / "tagged/exclude/package.xml").is_file()
        assert (root / "tagged/exclude/COLCON_IGNORE").read_text() == IGNORE_CONTENT
        assert {p.name for p in find_packages(str(root / "tagged")).values()} == {"keep"}


def test_resume_preserves_edits_and_clean_replaces_them(tmp_path, configuration):
    index, recipes = configuration
    src = tmp_path / "src"
    pull_distro_repositories(src, recipes, index)
    checkout = src / "ros2/branch"
    git(checkout, "checkout", "-b", "my-fix")
    (checkout / "README").write_text("My local fix\n")
    (checkout / "untracked").write_text("Keep me\n")
    pull_distro_repositories(src, recipes, index)
    assert git(checkout, "branch", "--show-current") == "my-fix"
    assert (checkout / "README").read_text() == "My local fix\n"
    assert (checkout / "untracked").exists()
    pull_distro_repositories(src, recipes, index, clean=True)
    assert not (checkout / "untracked").exists()
    assert (checkout / "README").read_text() == "Second revision\n"


def test_clone_failure_is_not_success(tmp_path, configuration):
    index, recipes = configuration
    distro = yaml.safe_load((tmp_path / "ros1.yaml").read_text())
    distro["repositories"]["branch"]["source"]["version"] = "nonexistent-ref"
    (tmp_path / "ros1.yaml").write_text(yaml.safe_dump(distro))
    src = tmp_path / "src"
    with pytest.raises(RuntimeError, match="vcs2l import failed"):
        pull_distro_repositories(src, recipes, index)
    assert not (src / "ros1/ros1_repositories_data.jsonl").exists()


def test_old_tarball_directory_is_not_silently_skipped(tmp_path, configuration):
    index, recipes = configuration
    src = tmp_path / "src"
    (src / "ros1/branch").mkdir(parents=True)
    with pytest.raises(ValueError, match="not a Git checkout"):
        pull_distro_repositories(src, recipes, index)


def test_filter_refreshes_only_its_own_markers(tmp_path):
    package(tmp_path / "a", "a")
    package(tmp_path / "b", "b")
    package(tmp_path / "c", "c")
    user_marker = tmp_path / "c/COLCON_IGNORE"
    user_marker.write_text("User ignore\n")
    filter_packages(tmp_path, ["a"])
    assert (tmp_path / "b/COLCON_IGNORE").read_text() == IGNORE_CONTENT
    filter_packages(tmp_path, ["b"])
    assert not (tmp_path / "b/COLCON_IGNORE").exists()
    assert (tmp_path / "a/COLCON_IGNORE").exists()
    filter_packages(tmp_path, [])
    assert not (tmp_path / "a/COLCON_IGNORE").exists()
    assert user_marker.read_text() == "User ignore\n"


def test_github_authentication(monkeypatch):
    url = "https://github.com/example/project.git"
    assert checkout_url(url, None) == "git@github.com:example/project.git"
    assert checkout_url(url, "test-token") == url
    assert checkout_url("git@github.com:example/project.git", None) == "git@github.com:example/project.git"
    assert checkout_url("https://example.com/project.git", None) == "https://example.com/project.git"
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "some.setting")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "keep")
    before = os.environ.copy()
    with pytest.raises(RuntimeError, match="test failure"):
        with github_authentication("test-token"):
            assert os.environ["GIT_CONFIG_COUNT"] == "2"
            assert os.environ["GIT_CONFIG_VALUE_0"] == "keep"
            assert os.environ["GIT_CONFIG_KEY_1"] == "http.https://github.com/.extraheader"
            assert os.environ["GIT_CONFIG_VALUE_1"].startswith("Authorization: Basic ")
            assert "test-token" not in os.environ["GIT_CONFIG_VALUE_1"]
            raise RuntimeError("test failure")
    assert os.environ == before
    with github_authentication(None):
        assert os.environ == before


@pytest.mark.parametrize("name", ["..", ".", "../escape", "/absolute", "nested/repo", ""])
def test_rejects_unsafe_directory_names(tmp_path, name):
    with pytest.raises(ValueError):
        child_directory(tmp_path, name)


def test_rejects_symlinked_directory(tmp_path):
    (tmp_path / "alias").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinked"):
        child_directory(tmp_path, "alias")

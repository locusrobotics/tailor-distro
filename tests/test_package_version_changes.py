import pytest

from catkin_pkg.package import Package

from tailor_distro.blossom import Graph, GraphPackage, package_content_hash


@pytest.mark.parametrize("relative_path,pattern", [
    ("Jenkinsfile", "Jenkinsfile"),
    ("nested/Jenkinsfile", "Jenkinsfile"),
    ("module.pyc", "*.pyc"),
    ("__pycache__/module.pyc", "__pycache__"),
    (".git/config", ".git"),
    ("build/output", "build"),
    ("nested/build/output", "build"),
    ("devel/output", "devel"),
    ("install/output", "install"),
    ("ci/job.yaml", "ci/*.yaml"),
])
def test_content_hash_ignores_recipe_patterns(tmp_path, relative_path, pattern):
    source = tmp_path / "source.cpp"
    source.write_text("source")
    baseline = package_content_hash(tmp_path, ignore_patterns=[pattern])
    ignored = tmp_path / relative_path
    ignored.parent.mkdir(parents=True, exist_ok=True)
    ignored.write_text("original")
    assert package_content_hash(tmp_path, ignore_patterns=[pattern]) == baseline
    ignored.write_text("changed")
    assert package_content_hash(tmp_path, ignore_patterns=[pattern]) == baseline
    ignored.unlink()
    assert package_content_hash(tmp_path, ignore_patterns=[pattern]) == baseline
    source.write_text("changed source")
    assert package_content_hash(tmp_path, ignore_patterns=[pattern]) != baseline


def test_content_hash_has_no_implicit_exclusions(tmp_path):
    baseline = package_content_hash(tmp_path)
    (tmp_path / "module.pyc").write_bytes(b"bytecode")
    assert package_content_hash(tmp_path) != baseline


def test_content_hash_preserves_dependency_and_path_changes(tmp_path):
    source = tmp_path / "source.cpp"
    source.write_text("source")
    baseline = package_content_hash(tmp_path, frozenset({"r:libfoo"}))
    assert package_content_hash(tmp_path, frozenset({"r:libbar"})) != baseline
    source.rename(tmp_path / "renamed.cpp")
    assert package_content_hash(tmp_path, frozenset({"r:libfoo"})) != baseline


@pytest.mark.parametrize("patterns", [None, [], ["Jenkinsfile"]])
def test_content_hash_recipe_and_yaml_round_trip(tmp_path, monkeypatch, patterns):
    package_dir = tmp_path / "src" / "ros1" / "example"
    package_dir.mkdir(parents=True)
    (package_dir / "package.xml").write_text("source")
    (package_dir / "Jenkinsfile").write_text("pipeline")
    recipe = {
        "common": {"apt_repo": "", "distributions": {"ros1": {"env": {}}}},
        "os": {"ubuntu": ["jammy"]},
    }
    if patterns is not None:
        recipe["common"]["package_contents_ignore_patterns"] = patterns
    monkeypatch.setattr(Graph, "__post_init__", lambda self: None)
    monkeypatch.setattr(
        "tailor_distro.blossom.topological_order",
        lambda root: [("example", Package(name="example", version="1.0.0"))],
    )
    graph, = Graph.from_recipe(recipe, tmp_path, "test", "20261109.000000", init_apt=False)
    assert graph.package_contents_ignore_patterns == (patterns or [])
    assert graph.packages["ros1"]["example"].sha == package_content_hash(
        package_dir, ignore_patterns=patterns or []
    )
    graph.write_yaml(tmp_path / "graphs")
    restored = Graph.from_yaml(tmp_path / "graphs" / f"{graph.name}.yaml")
    assert restored.package_contents_ignore_patterns == (patterns or [])
    assert restored.packages == graph.packages

# Arbitrary dates to test
OLD_BUILD_DATE = "20260506.000000"
NEW_BUILD_DATE = "20260507.000000"


def test_git_sha_change():
    """
    Tests that if the SHA changes the package is included in the build list, even if the version is the same.
    """
    a = GraphPackage(
        "pkg_a",
        "0.0.0",
        "abc1234",
        ros_version="ros1",
        apt_candidate_version=f"0.0.0-{OLD_BUILD_DATE}+git1234567",
        path="",
        apt_depends=[],
        source_depends=[],
    )

    graph = Graph(
        "ubuntu",
        "jammy",
        "test",
        NEW_BUILD_DATE,
        apt_repo="",
        init_apt=False,
        packages={
            "ros1": {
                "pkg_a": a,
            }
        },
    )
    graph.finalize()

    build_list, download_list = graph.build_list("ros1", rebuild_all=False)

    assert "pkg_a" in build_list
    assert build_list["pkg_a"].name == "pkg_a"

    debian_version = a.debian_version(NEW_BUILD_DATE)
    assert debian_version == f"0.0.0-{NEW_BUILD_DATE}+gitabc1234"


def test_pkg_version_downgrade():
    """
    Tests that if the package version is downgraded the new package version includes an epoch
    to ensure it is considered newer than the APT version.
    """
    a = GraphPackage(
        "pkg_a",
        "0.0.0",
        "abc1234",
        ros_version="ros1",
        apt_candidate_version=f"0.0.1-{OLD_BUILD_DATE}+git1234567",
        path="",
        apt_depends=[],
        source_depends=[],
    )

    graph = Graph(
        "ubuntu",
        "jammy",
        "test",
        NEW_BUILD_DATE,
        apt_repo="",
        init_apt=False,
        packages={
            "ros1": {
                "pkg_a": a,
            }
        },
    )
    graph.finalize()

    build_list, download_list = graph.build_list("ros1", rebuild_all=False)

    assert "pkg_a" in build_list
    assert build_list["pkg_a"].name == "pkg_a"

    debian_version = a.debian_version(NEW_BUILD_DATE)
    assert debian_version == f"1:0.0.0-{NEW_BUILD_DATE}+gitabc1234"


def test_pkg_version_downgrade_with_epoch():
    """
    Tests that if the package version with an existing epoch is downgraded the new package version
    includes an epoch incremented by 1.
    """
    a = GraphPackage(
        "pkg_a",
        "0.0.0",
        "abc1234",
        ros_version="ros1",
        apt_candidate_version=f"1:0.0.1-{OLD_BUILD_DATE}+git1234567",
        path="",
        apt_depends=[],
        source_depends=[],
    )

    graph = Graph(
        "ubuntu",
        "jammy",
        "test",
        NEW_BUILD_DATE,
        apt_repo="",
        init_apt=False,
        packages={
            "ros1": {
                "pkg_a": a,
            }
        },
    )
    graph.finalize()

    build_list, download_list = graph.build_list("ros1", rebuild_all=False)

    assert "pkg_a" in build_list
    assert build_list["pkg_a"].name == "pkg_a"

    debian_version = a.debian_version(NEW_BUILD_DATE)
    assert debian_version == f"2:0.0.0-{NEW_BUILD_DATE}+gitabc1234"


if __name__ == "__main__":
    test_git_sha_change()
    test_pkg_version_downgrade()
    test_pkg_version_downgrade_with_epoch()

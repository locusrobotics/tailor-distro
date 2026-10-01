from tailor_distro.blossom import Graph, GraphPackage, package_content_hash


def test_git_metadata_does_not_change_package_hash(tmp_path):
    (tmp_path / "source.cpp").write_text("int main() {}\n")
    before = package_content_hash(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git/HEAD").write_text("ref: refs/heads/main\n")
    assert package_content_hash(tmp_path) == before
    (tmp_path / ".git/HEAD").write_text("ref: refs/heads/local-fix\n")
    assert package_content_hash(tmp_path) == before

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

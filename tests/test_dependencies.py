from tailor_distro.blossom import Graph, GraphPackage

# Arbitrary dates to test
OLD_BUILD_DATE = "20260506.000000"
NEW_BUILD_DATE = "20260507.000000"


def test_all_apt_depends():
    """
    Tests that all apt depends are included in the query, even nested depends.
    """
    a = GraphPackage(
        "pkg_a",
        "0.0.0",
        "abc1234",
        ros_version="ros1",
        apt_candidate_version=f"0.0.0-{OLD_BUILD_DATE}+git1234567",
        path="",
        apt_depends=["b:apt_depend1"],
        source_depends=["b:pkg_b"],
    )
    b = GraphPackage(
        "pkg_b",
        "0.0.0",
        "abc1234",
        ros_version="ros1",
        apt_candidate_version=f"0.0.0-{OLD_BUILD_DATE}+git1234567",
        path="",
        apt_depends=["b:apt_depend2"],
        source_depends=[],
    )

    graph = Graph(
        "ubuntu",
        "jammy",
        "test",
        NEW_BUILD_DATE,
        apt_repo="",
        init_apt=False,
        packages={"ros1": {"pkg_a": a, "pkg_b": b}},
    )
    graph.finalize()

    apt_depends = graph.all_apt_depends("pkg_a", "ros1")
    assert "apt_depend1" in apt_depends
    assert "apt_depend2" in apt_depends


def test_run_and_build_depends():
    """
    Tests that run/build depends are included and can be queried separately.
    """
    a = GraphPackage(
        "pkg_a",
        "0.0.0",
        "abc1234",
        ros_version="ros1",
        apt_candidate_version=f"0.0.0-{OLD_BUILD_DATE}+git1234567",
        path="",
        apt_depends=["r:apt_run_depend1", "b:apt_build_depend1"],
        source_depends=["r:source_run_depend1", "b:source_build_depend1"],
    )

    source_run_depends = a.run_depends(types=["source"])
    assert "source_run_depend1" in source_run_depends

    source_build_depends = a.build_depends(types=["source"])
    assert "source_build_depend1" in source_build_depends

    apt_run_depends = a.run_depends(types=["apt"])
    assert "apt_run_depend1" in apt_run_depends

    apt_build_depends = a.build_depends(types=["apt"])
    assert "apt_build_depend1" in apt_build_depends


if __name__ == "__main__":
    test_all_apt_depends()
    test_run_and_build_depends()

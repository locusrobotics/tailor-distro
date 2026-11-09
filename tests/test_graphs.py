from tailor_distro.blossom import Graph, GraphPackage


def test_circular_dep():
    a = GraphPackage("pkg_a", "0.0.0", "abc1234", path="", ros_version="ros1",
                     apt_depends=[], source_depends=["r:pkg_b"])
    b = GraphPackage("pkg_b", "0.0.0", "abc1234", path="", ros_version="ros1",
                     apt_depends=[], source_depends=["r:pkg_c"])
    c = GraphPackage("pkg_c", "0.0.0", "abc1234", path="", ros_version="ros1",
                     apt_depends=[], source_depends=["r:pkg_a"])

    graph = Graph(
        "ubuntu", "jammy", "ros1", "release", "abc123", init_apt=False,
        packages={"ros1": {"pkg_a": a, "pkg_b": b, "pkg_c": c}},
    )
    graph.finalize()


def test_build_list_download_list_only_includes_build_dependencies():
    apt_version = "1.0-20260101.000000+srcabc1234"

    # "app" needs to be rebuilt (no apt candidate). It requires "lib_build" as a
    # build dependency, which in turn requires "toolchain" as a build dependency.
    # "lib_runtime" is an unrelated, unchanged runtime dependency of "app" that
    # isn't needed to build anything.
    app = GraphPackage("app", "0.0.0", "abc1234", path="", ros_version="ros2",
                        apt_depends=[], source_depends=["b:lib_build", "r:lib_runtime"])
    lib_build = GraphPackage("lib_build", "0.0.0", "abc1234", path="", ros_version="ros2",
                              apt_depends=[], source_depends=["b:toolchain"],
                              apt_candidate_version=apt_version)
    toolchain = GraphPackage("toolchain", "0.0.0", "abc1234", path="", ros_version="ros2",
                              apt_depends=[], source_depends=[],
                              apt_candidate_version=apt_version)
    lib_runtime = GraphPackage("lib_runtime", "0.0.0", "abc1234", path="", ros_version="ros2",
                                apt_depends=[], source_depends=[],
                                apt_candidate_version=apt_version)

    graph = Graph(
        "ubuntu", "jammy", "ros1", "release", "abc123", init_apt=False,
        packages={"ros2": {
            "app": app,
            "lib_build": lib_build,
            "toolchain": toolchain,
            "lib_runtime": lib_runtime,
        }},
    )
    graph.finalize()

    build_list, download_list = graph.build_list("ros2")

    assert sorted(build_list.keys()) == ["app"]
    assert sorted(download_list.keys()) == ["lib_build", "toolchain"]


if __name__ == "__main__":
    test_circular_dep()
    test_build_list_download_list_only_includes_build_dependencies()

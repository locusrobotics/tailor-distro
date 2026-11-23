import unittest

from types import SimpleNamespace

from tailor_distro.blossom import Graph, collect_root_packages

class TestPackageSelection(unittest.TestCase):
    def test_empty_list(self):
        recipe = {
            "flavours": {
                "empty_root_packages": {
                    "distributions": {
                        "ros1": {
                            "root_packages": []
                        }
                    }
                }
            }
        }
        self.assertEqual(collect_root_packages(recipe, "ros1"), [])

    def test_non_empty_list(self):
        recipe = {
            "flavours": {
                "non_empty_root_packages": {
                    "distributions": {
                        "ros1": {
                            "root_packages": ["package1", "package2"]
                        }
                    }
                }
            }
        }
        self.assertEqual(collect_root_packages(recipe, "ros1"), ["package1", "package2"])

    def test_missing_root_packages(self):
        recipe = {
            "flavours": {
                "missing_root_packages": {
                    "distributions": {
                        "ros1": {}
                    }
                }
            }
        }

        with self.assertRaises(RuntimeError):
            collect_root_packages(recipe, "ros1")

    def test_absent_distro_returns_none(self):
        recipe = {
            "flavours": {
                "ros2_only": {
                    "distributions": {
                        "ros2": {
                            "root_packages": ["pkg2"]
                        }
                    }
                }
            }
        }
        self.assertIsNone(collect_root_packages(recipe, "ros1"))


def _fake_graph():
    def pkg(name, ros1_depends=[]):
        return SimpleNamespace(name=name, ros1_depends=list(ros1_depends))

    packages = {
        "ros1": {
            "bridge_core": pkg("bridge_core"),
            "ros1_other": pkg("ros1_other"),
        },
        "ros2": {
            "app": pkg("app"),
            "app_dep": pkg("app_dep", ros1_depends=["bridge_core"]),
            "unrelated": pkg("unrelated"),
        },
    }

    depends = {("app", "ros2"): ["app_dep"]}

    return SimpleNamespace(
        packages=packages,
        all_source_depends=lambda name, distro: depends.get((name, distro), []),
    )


class TestRecipeRootPackages(unittest.TestCase):
    def test_absent_ros1_seeded_from_ros2_closure(self):
        recipe = {
            "flavours": {
                "flavour": {
                    "distributions": {
                        "ros2": {"root_packages": ["app"]}
                    }
                }
            }
        }
        graph = _fake_graph()
        # app -> app_dep -> (ros1) bridge_core; ros1 absent from recipe
        self.assertEqual(Graph.recipe_root_packages(graph, recipe, "ros1"), ["bridge_core"])
        self.assertEqual(Graph.recipe_root_packages(graph, recipe, "ros2"), ["app"])

    def test_absent_ros1_with_no_cross_deps_returns_none(self):
        recipe = {
            "flavours": {
                "flavour": {
                    "distributions": {
                        "ros2": {"root_packages": ["unrelated"]}
                    }
                }
            }
        }
        self.assertIsNone(Graph.recipe_root_packages(_fake_graph(), recipe, "ros1"))

    def test_ros1_roots_merged_with_cross_deps(self):
        recipe = {
            "flavours": {
                "flavour": {
                    "distributions": {
                        "ros1": {"root_packages": ["ros1_other"]},
                        "ros2": {"root_packages": ["app"]},
                    }
                }
            }
        }
        roots = Graph.recipe_root_packages(_fake_graph(), recipe, "ros1")
        self.assertEqual(sorted(roots), ["bridge_core", "ros1_other"])

    def test_explicit_build_all_ros1_unchanged(self):
        recipe = {
            "flavours": {
                "flavour": {
                    "distributions": {
                        "ros1": {"root_packages": []},
                        "ros2": {"root_packages": ["app"]},
                    }
                }
            }
        }
        self.assertEqual(Graph.recipe_root_packages(_fake_graph(), recipe, "ros1"), [])

if __name__ == "__main__":
    unittest.main()

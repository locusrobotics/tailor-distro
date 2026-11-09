from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from catkin_pkg.package import parse_package_string

from tailor_distro.blossom import Graph, GraphPackage


DEPENDENCY_ROLES = [
    ("<exec_depend>shared</exec_depend>", {"r:"}),
    ("<build_depend>shared</build_depend>", {"b:"}),
    ("<exec_depend>shared</exec_depend><build_depend>shared</build_depend>", {"r:", "b:"}),
    ("<depend>shared</depend>", {"r:", "b:"}),
    ('<exec_depend>shared</exec_depend><build_depend condition="$ENABLED == 1">shared</build_depend>', {"r:"}),
]


class TestDependencyRoles(TestCase):
    def test_add_package_preserves_dependency_roles(self):
        for dependency_xml, prefixes in DEPENDENCY_ROLES:
            for resolution in ("apt", "source", "empty_rules_source"):
                with self.subTest(dependency_xml=dependency_xml, resolution=resolution):
                    with TemporaryDirectory() as directory:
                        self.check_dependency_roles(Path(directory), dependency_xml, prefixes, resolution)

    def check_dependency_roles(self, tmp_path, dependency_xml, prefixes, resolution):
        package = parse_package_string(f"""
            <package format="3">
                <name>consumer</name>
                <version>1.0.0</version>
                <description>Dependency role test</description>
                <maintainer email="test@example.com">Test</maintainer>
                <license>BSD</license>
                {dependency_xml}
            </package>
        """)
        with patch.object(Graph, "__post_init__", return_value=None):
            graph = Graph("ubuntu", "jammy", "test", "20261021.000000", "", init_apt=False)
        graph._rosdep_view = Mock()
        if resolution == "source":
            graph._rosdep_view.lookup.side_effect = KeyError("shared")
        else:
            rules = ["libshared-dev"] if resolution == "apt" else []
            graph._rosdep_view.lookup.return_value.get_rule_for_platform.return_value = ("apt", rules)
        if resolution == "empty_rules_source":
            graph.packages["ros1"] = {
                "shared": GraphPackage("shared", "1.0.0", "abc1234", "", "ros1", [], []),
            }

        graph.add_package(package, "ros1", tmp_path, tmp_path, conditions={"ENABLED": "0"})

        result = graph.packages["ros1"]["consumer"]
        name = "libshared-dev" if resolution == "apt" else "shared"
        expected = {f"{prefix}{name}" for prefix in prefixes}
        self.assertEqual(set(result.apt_depends), expected if resolution == "apt" else set())
        self.assertEqual(set(result.source_depends), set() if resolution == "apt" else expected)
        self.assertEqual(set(result.run_depends()), {name} if "r:" in prefixes else set())
        self.assertEqual(set(result.build_depends()), {name} if "b:" in prefixes else set())

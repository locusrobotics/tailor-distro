import unittest

from tailor_distro.build_packages import collect_root_packages

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

if __name__ == "__main__":
    unittest.main()

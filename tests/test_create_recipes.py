import yaml

from tailor_distro.create_recipes import create_recipes


def test_flavour_os_overrides_global_os(tmp_path):
    recipes = {
        'os': {'ubuntu': ['jammy']},
        'flavours': {
            'dev': {'distributions': {'ros1': {'root_packages': []}}},
            'build': {
                'distributions': {'ros1': {'root_packages': []}},
                'os': {'ubuntu': ['noble']},
            },
        },
        'common': {'distributions': {'ros1': {'os': []}}},
    }

    create_recipes(recipes, tmp_path, 'track', 'label', '1.0.0')

    assert {path.name for path in tmp_path.iterdir()} == {
        'dev-jammy-label.yaml',
        'build-noble-label.yaml',
    }
    assert yaml.safe_load((tmp_path / 'dev-jammy-label.yaml').read_text())['os_version'] == 'jammy'
    assert yaml.safe_load((tmp_path / 'build-noble-label.yaml').read_text())['os_version'] == 'noble'

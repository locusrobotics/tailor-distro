#!/usr/bin/python3

from glob import glob
from os.path import basename, splitext
from setuptools import find_packages, setup

setup(
    name='tailor-distro',
    version='0.0.0',
    description='Build rosdistro bundles',
    license='Proprietary',
    author='Paul Bovbel',
    author_email='pbovbel@locusrobotics.com',
    url='https://github.com/locusrobotics/tailor-distro',
    packages=find_packages('src'),
    package_dir={'': 'src'},
    py_modules=[splitext(basename(path))[0] for path in glob('src/*.py')],
    install_requires=[
        'bloom',
        'catkin_pkg',
        'Jinja2',
        'PyYaml',
        'rosdistro',
        'vcstool',
    ],
    setup_requires=["pytest-runner"],
    tests_require=[
        "pytest",
        "pytest-mypy",
        "pytest-pep8",
    ],
    entry_points={
        'console_scripts': [
            'create_recipes = tailor_distro.create_recipes:main',
            'pull_distro_repositories = tailor_distro.pull_distro_repositories:main',
            'generate_bundle_templates = tailor_distro.generate_bundle_templates:main',
            'publish_packages = tailor_distro.publish_packages:main',
        ]
    }
)

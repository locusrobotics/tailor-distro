from setuptools import setup

setup(
    name='tailor-distro',
    packages=['tailor_distro'],
    version='0.0.0',
    description='Build rosdistro bundles',
    license='Proprietary',
    author='Paul Bovbel',
    author_email='pbovbel@locusrobotics.com',
    url='https://github.com/locusrobotics/tailor-distro',
    install_requires=[
        'bloom',
        'catkin_pkg',
        'Jinja2',
        'PyYaml',
        'rosdistro',
        'vcstool'
    ],
    entry_points={
        'console_scripts': [
            'create_recipes = tailor_distro.create_recipes:main',
            'pull_distro_repositories = tailor_distro.pull_distro_repositories:main',
            'generate_bundle_templates = tailor_distro.generate_bundle_templates:main'
        ]
    }
)

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
        'rosdistro',
        'PyYaml',
        'Jinja2',
        'vcstool'
    ],
    entry_points={
      'console_scripts': [
          'pull_distro_repositories = tailor_distro.pull_distro_repositories:main',
          'generate_bundle_templates = tailor_distro.generate_bundle_templates:main'
      ]
    }
)

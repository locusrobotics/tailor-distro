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
        'vcstool'
    ],
    entry_points={
      'console_scripts': [
          'pull_distro = tailor_distro.pull_distro:main'
      ]
    }
)

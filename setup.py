from setuptools import setup

install_reqs = [
    # library
    'torch',
    'moviepy',
    'Pillow',
    'tensorboard==2.1.0',
    'tensorboardX==1.9',
    'mujoco-py',
    'optuna',
    'numpy',
    'scipy==1.7.3',
    'typing_extensions',
    'meshcat',
    'matplotlib',
    'threadpoolctl',
    'click',
    'pywavefront',
    # documentation
    'pydeps',
    'networkx',
    'Sphinx',
    'sphinx-autodoc-typehints',
    'sphinx-rtd-theme',
    'sphinx-toolbox',
    'sphinxcontrib-napoleon',
    # development
    'yapf',
    'pylint',
    'mypy',
]

try:
    import pydrake

    print('USING FOUND DRAKE VERSION')
except ModuleNotFoundError as e:
    install_reqs += ['drake']

dependency_links = [
    'git+https://github.com/DAIRLab/drake-pytorch.git',
    'git+https://github.com/mshalm/diffqcqp.git'
]

setup(
    name='dair_pll',
    version='0.0.1',
    packages=['dair_pll'],
    install_requires=install_reqs,
    dependency_links=dependency_links
)

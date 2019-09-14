from __future__ import absolute_import, division, print_function

from setuptools import find_packages, setup

setup(
    name='jobrunner',
    version='1.0.5',
    description='Job runner with logging',
    packages=find_packages(exclude=[
        'jobrunner.test',
        'jobrunner.test.*',
    ]),
    install_requires=open("requirements.in").readlines(),
    tests_require=open("requirements.testing.in").readlines(),
    test_suite='nose.collector',
    scripts=[
        'job',
    ],
)

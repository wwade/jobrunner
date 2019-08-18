from __future__ import absolute_import, division, print_function

from setuptools import find_packages, setup

setup(
    name='jobrunner',
    version='1.0.2',
    description='Job runner with logging',
    packages=find_packages(exclude=[
        'jobrunner.test',
        'jobrunner.test.*',
    ]),
    install_requires=[
        'dateutils',
        'simplejson',
    ],
    test_suite='nose.collector',
    tests_require=[
        'mock',
        'pytest',
    ],
    scripts=[
        'job',
    ],
)

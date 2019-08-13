from __future__ import absolute_import, division, print_function
from setuptools import setup, find_packages

setup(
    name='jobrunner',
    version='1.0.1',
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
        'nose',
    ],
    scripts=[
        'job',
    ],
)

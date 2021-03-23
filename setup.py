from __future__ import absolute_import, division, print_function

from setuptools import find_packages, setup

setup(
    name='async-jobrunner',
    version='2.2.0',
    description='Job runner with logging',
    packages=find_packages(exclude=[
        'jobrunner.test',
        'jobrunner.test.*',
    ]),
    install_requires=[
        'chardet',
        'dateutils',
        'importlib-metadata',
        'requests<2.26.0',
        'simplejson<3.18.0',
        'six',
    ],
    entry_points={
        "console_scripts": [
            "job = jobrunner.main:main",
            "chatmail = jobrunner.mail.chat:main",
        ],
    }
)

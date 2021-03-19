from __future__ import absolute_import, division, print_function

from setuptools import find_packages, setup

setup(
    name='jobrunner',
    version='2.1.0',
    description='Job runner with logging',
    packages=find_packages(exclude=[
        'jobrunner.test',
        'jobrunner.test.*',
    ]),
    install_requires=[
        'six',
        'dateutils',
        'importlib-metadata',
        'requests<=2.23.0',
        'simplejson<=3.3.0',
    ],
    entry_points={
        "console_scripts": [
            "job = jobrunner.main:main",
            "chatmail = jobrunner.mail.chat:main",
        ],
    }
)

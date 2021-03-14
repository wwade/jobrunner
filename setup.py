from __future__ import absolute_import, division, print_function

from setuptools import find_packages, setup

setup(
    name='jobrunner',
    version='1.0.6',
    description='Job runner with logging',
    packages=find_packages(exclude=[
        'jobrunner.test',
        'jobrunner.test.*',
    ]),
    install_requires=[
       'dateutils',
       'requests<=2.23.0',
       'simplejson<=3.3.0',
    ],
    scripts=[
        'job',
    ],
    entry_points={
        "console_scripts": [
            "chatmail = jobrunner.mail.chat:main",
        ],
    }
)

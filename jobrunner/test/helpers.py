from __future__ import absolute_import, division, print_function

import os

HOSTNAME = 'host.example.com'
HOME = '/home/me'
USER = 'me'


def resetEnv():
    os.environ['HOME'] = HOME
    os.environ['HOSTNAME'] = HOSTNAME
    os.environ['JOBRUNNER_STATE_DIR'] = '/tmp/BADDIR'
    os.environ['USER'] = USER
    if 'WP' in os.environ:
        del os.environ['WP']

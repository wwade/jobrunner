from __future__ import absolute_import, division, print_function

import logging
import os
import sys


def getLogger(name):
    return logging.getLogger(name)


def setup(logDir, debugLogFileName, debug=False):
    fmt = (
        '+%(process)-6d %(levelname)-9s '
        '%(name)-20s %(filename)20s:%(lineno)-5d '
        '[%(asctime)s] %(message)s')
    if debug:
        logFileName = os.path.join(logDir, debugLogFileName)
        logging.basicConfig(
            filename=logFileName,
            level=logging.DEBUG,
            format=fmt)
    else:
        logging.basicConfig(stream=sys.stderr, level=logging.ERROR, format=fmt)

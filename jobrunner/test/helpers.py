from __future__ import absolute_import, division, print_function

from contextlib import contextmanager
import os
import sys

from six.moves import StringIO

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


@contextmanager
def capturedOutput():
    ''' Used to capture stdout or stderr.
    eg.
    with capturedOutput() as (out, err):
        print("foo")

    self.assertEqual(out.getvalue(), "foo")
    '''
    newOut, newErr = StringIO(), StringIO()
    oldOut, oldErr = sys.stdout, sys.stderr
    try:
        sys.stdout, sys.stderr = newOut, newErr
        yield sys.stdout, sys.stderr
    finally:
        sys.stdout, sys.stderr = oldOut, oldErr

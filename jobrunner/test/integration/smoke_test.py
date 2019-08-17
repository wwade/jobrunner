from __future__ import absolute_import, division, print_function

from contextlib import contextmanager
from shutil import rmtree
from subprocess import check_call, check_output, STDOUT, CalledProcessError
from tempfile import mkdtemp
from unittest import TestCase, main
import os
import time

HOSTNAME = 'host.example.com'
HOME = '/home/me'

EXAMPLE_RCFILE = """\
[mail]
program=mail-program
domain=ex.com
"""


def setUpModule():
    os.environ['JOBRUNNER_STATE_DIR'] = '/tmp/BADDIR'
    os.environ['HOME'] = HOME
    os.environ['HOSTNAME'] = HOSTNAME


class Env(object):
    def __init__(self, tmpDir):
        self.tmpDir = tmpDir

    def path(self, fileName):
        return os.path.join(self.tmpDir, fileName)


def curDir():
    return os.path.dirname(__file__)


def awaitFile(fileName, exitCode):
    return ['./await_file.py', fileName, str(exitCode)]


def inactiveCount():
    return int(run(['job', '--count'], capture=True))


@contextmanager
def testEnv():
    tmpDir = mkdtemp()
    os.environ['JOBRUNNER_STATE_DIR'] = tmpDir
    os.chdir(curDir())
    try:
        print('tmpDir', tmpDir)
        yield Env(tmpDir)
    finally:
        print('rmTree', tmpDir)
        rmtree(tmpDir)
        os.environ['JOBRUNNER_STATE_DIR'] = '/tmp/BADDIR'


def run(cmd, capture=False):
    print('+', ' '.join(cmd))
    try:
        if capture:
            return check_output(cmd, stderr=STDOUT)
        else:
            return check_call(cmd)
    except CalledProcessError as er:
        print(er.output)
        raise


def waitFor(func, timeout=10.0, failArg=True):
    interval = 0.1
    for _ in range(int(timeout / interval)):
        if func():
            return
        time.sleep(interval)
    if failArg:
        func(fail=True)
    raise Exception('timed out waiting for %r' % func)


def activeJobs():
    return run(['job', '-l'], capture=True)


def noJobs(fail=False):
    jobs = activeJobs().splitlines()
    if fail:
        print(jobs)
    return jobs[0] == '(None)'


class SmokeTest(TestCase):
    def testBasic(self):
        with testEnv() as env:
            waitFile1 = env.path('waitFile1')
            waitFile2 = env.path('waitFile2')
            run(['job'] + awaitFile(waitFile1, 1))
            run(['job'] + awaitFile(waitFile2, 0))
            run(['job', '-B.', 'true'])
            run(['job', '-B.', 'false'])
            notFound = env.path('canaryNotFound')
            run(['job', '-B.', '-c', 'touch {}'.format(notFound)])
            found = env.path('canaryFound')
            touchFound = 'touch {}'.format(found)
            run(['job', '-c', touchFound, '-b', 'waitFile1', '-B', 'waitFile2', ])
            waitFor(lambda: touchFound in activeJobs(), failArg=False)
            time.sleep(1)
            open(waitFile1, 'w').write('')
            open(waitFile2, 'w').write('')
            waitFor(noJobs)
            print(run(['job', '-L'], capture=True))
            self.assertEqual(6, inactiveCount())
            self.assertTrue(os.path.exists(found))
            self.assertFalse(os.path.exists(notFound))


if __name__ == '__main__':
    main()

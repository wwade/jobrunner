from __future__ import absolute_import, division, print_function

from contextlib import contextmanager
import os
import re
from shutil import rmtree
from subprocess import STDOUT, CalledProcessError, check_call, check_output
from tempfile import NamedTemporaryFile, mkdtemp
import time
from unittest import TestCase, main

import simplejson as json

from ..helpers import resetEnv

HOSTNAME = 'host.example.com'
HOME = '/home/me'

EXAMPLE_RCFILE = """\
[mail]
program=mail-program
domain=ex.com
"""


def setUpModule():
    resetEnv()
    os.environ['HOME'] = HOME
    os.environ['HOSTNAME'] = HOSTNAME
    os.environ['JOBRUNNER_STATE_DIR'] = '/tmp/BADDIR'


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
    except CalledProcessError as error:
        print(error.output)
        raise


def jobf(*cmd):
    jobCmd = ['job', '--foreground'] + list(cmd)
    return run(jobCmd, capture=True)


def job(*cmd):
    jobCmd = ['job'] + list(cmd)
    return run(jobCmd, capture=True)


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
    jobs = activeJobs()
    if fail:
        print(jobs)
    return jobs.splitlines()[0] == '(None)'


def lastKey():
    [ret] = run(['job', '-K'], capture=True).splitlines()
    return ret


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


class RunExecOptionsTest(TestCase):
    """
    Test the following (exec related) options
        --quiet
        --foreground
        -v
        --command
        --retry
        --reminder
        --done
        --key
        --state-dir
        --tw
        --tp
        --blocked-by
        --blocked-by-success
        --wait
        --watch
        --pid
        --input
        --int
        --stop
        --delete
        --debugLocking
        --auto-job
    """
    # TODO


MAIL_CONFIG = """
[mail]
program=./send_email.py
domain=example.com
"""


class RunMailTest(TestCase):
    """
    Test mail-related options

        --mail
        --to
        --cc
        --rc-file
    """

    @staticmethod
    def getMailArgs(mailKey):
        lastLog = job('-g', mailKey).splitlines()[0]
        return json.load(open(lastLog))

    def test(self):
        with testEnv():
            rcFile = NamedTemporaryFile()
            rcFile.write(MAIL_CONFIG)
            rcFile.flush()
            # --mail
            # --rc-file
            jobf('true')
            jobf('--rc-file', rcFile.name, '--mail', '.')
            args1 = self.getMailArgs(lastKey())
            self.assertIn('-s', args1)
            self.assertIn('-a', args1)
            self.assertIn('me', args1)
            # --to
            # --cc
            jobf('--rc-file', rcFile.name, '--mail', 'true', '--to', 'someone',
                 '--cc', 'another')
            args2 = self.getMailArgs(lastKey())
            print(repr(args2))
            self.assertIn('-s', args2)
            self.assertIn('-a', args2)
            self.assertNotIn('me', args2)
            self.assertIn('someone', args2)
            self.assertIn('another@example.com', args2)


class UnTestedOptionsTest(TestCase):
    """
    Following are not (yet) tested

        --dot
        --png
        --svg
        --isolate
        --debug
        --get-all-logs
    """
    # TODO


class RunNonExecOptionsTest(TestCase):
    """
    Test the following (non-exec related) options

        --help
        --count
        --last-key
        --list
        --index
        --list-inactive
        --show
        --get-log
        --info
        --prune
        --prune-except
        --since-checkpoint
        --set-checkpoint
        --activity
        --activity-window
    """

    def testRunAllNonExecOptions(self):
        with testEnv():
            # --last-key
            jobf('-v', 'echo', 'first')
            firstKey = lastKey()
            jobf('echo', 'second')
            secondKey = lastKey()
            self.assertNotEqual(firstKey, secondKey)

            # --help
            self.assertIn("Job runner with logging", job('--help'))

            # --count
            self.assertEqual(int(job('--count')), 2)

            # --list
            self.assertEqual('(None)', job('--list').strip())

            # --index
            # --get-log
            [file1] = job('--index', '1').splitlines()
            [firstLog] = job('--get-log', firstKey).splitlines()
            self.assertEqual(file1, firstLog)
            [file2] = job('--index', '0').splitlines()
            for (fileName, value) in ((file1, "first"), (file2, "second")):
                self.assertIn(value, open(fileName, 'r').read())
            multiLogFiles = job('-g', firstKey, '-g', secondKey).split()
            self.assertEqual(len(multiLogFiles), 2)
            self.assertNotEqual(multiLogFiles[0], multiLogFiles[1])

            # --list-inactive
            listInactive = job('--list-inactive')
            self.assertIn("echo first", listInactive)
            self.assertIn("echo second", listInactive)
            listInactiveVerbose = job('--list-inactive', '-v')
            progEchoRe = re.compile(r'^Program\s*echo$', re.M)
            self.assertRegexpMatches(listInactiveVerbose, progEchoRe)

            # --show
            self.assertRegexpMatches(job('--show', secondKey), progEchoRe)
            # --info
            self.assertIn("activeJobs", job('--info'))

            #  --set-checkpoint
            job('--set-checkpoint', '.')
            # --since-checkpoint
            self.assertIn(
                '(None)', job(
                    '--since-checkpoint', '--list-inactive'))

            # --prune-except
            job('--prune-except', '1')
            jobList = job('--list-inactive').splitlines()
            self.assertEqual(jobList, [jobList[0]])

            # --prune
            oldList = job('--list-inactive').splitlines()
            job('--prune').splitlines()
            newList = job('--list-inactive').splitlines()
            self.assertEqual(oldList, newList)

            # --activity
            # --activity-window


if __name__ == '__main__':
    main()

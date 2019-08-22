from __future__ import absolute_import, division, print_function

from contextlib import contextmanager
import os
from pprint import pprint
import re
from shutil import rmtree
from subprocess import (
    PIPE,
    STDOUT,
    CalledProcessError,
    Popen,
    check_call,
    check_output,
)
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

    def path(self, subPath):
        return os.path.join(self.tmpDir, subPath)


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

    def test(self):
        # pylint: disable=too-many-statements
        with testEnv() as env:
            os.environ['TMUX_PANE'] = 'pane1'
            # --quiet
            # --foreground
            out = jobf('--quiet', 'true')
            self.assertEqual(out, '')

            # --command
            out = jobf('--command', 'false || true')
            self.assertIn('return code: 0', out)

            # --retry
            out = jobf('--retry', '||')
            self.assertIn('false || true', out)
            self.assertIn('return code: 0', out)

            # --reminder
            # --done
            jobf('--reminder', 'do something')
            out = jobf('-l')
            self.assertIn('Reminder: do something', out)
            jobf('--done', 'something')
            out = jobf('-l')
            self.assertNotIn('Reminder: do something', out)

            # --key
            jobf('--key', 'explicitTrue', 'true')
            self.assertEqual('explicitTrue', lastKey())

            # --state-dir
            newStateDir = env.path('newStateDir')
            jobf('--state-dir', newStateDir, 'true')
            out = jobf('--state-dir', newStateDir, '--count')
            self.assertEqual(int(out), 1)

            # --tw
            out = jobf('--tw', '-L')
            # Without a workspaceIdentity plugin, all workspaces should match.
            self.assertIn('[explicitTrue]', out)

            # --tp
            os.environ['TMUX_PANE'] = 'pane2'
            out = jobf('--tp', '-L')
            self.assertIn('(None)', out)

            # --blocked-by
            # --blocked-by-success
            # See SmokeTest

            # --pid
            # --int
            run(['job', 'sleep', '60'])
            out = jobf('--pid', 'sleep')
            self.assertIn('sleep', out)
            job('--int', 'sleep')
            waitFor(noJobs)

            # --delete
            # --stop
            with self.assertRaises(CalledProcessError) as error:
                jobf('--stop', 'explicitTrue')
            self.assertIn('Jobs not active:', error.exception.output)

            jobf('--delete', 'explicitTrue')
            with self.assertRaises(CalledProcessError) as error:
                jobf('--show', 'explicitTrue')
                self.assertIn('No job for key', error.exception.output)

            # --auto-job
            # --debugLocking
            out = jobf('--auto-job', '--debugLocking', 'true')
            print(out)

            inFile = NamedTemporaryFile()
            data = 'this is the input\n'
            inFile.write('this is the input\n')
            inFile.flush()
            # --input
            jobf('--input', inFile.name, '--', 'cat')
            catOutFile = jobf('-g', 'cat').strip()
            outData = open(catOutFile).read()
            self.assertEqual(outData, data)

            # --watch
            # --wait
            print('+ job --watch')
            sub = Popen(['job', '--watch'], stdout=PIPE)
            jobf('sleep', '3')
            out = ''
            out += sub.stdout.read(10)
            out += sub.stdout.read(10)
            out += sub.stdout.read(10)
            job('--wait', 'sleep')
            time.sleep(2)
            sub.terminate()
            sub.wait()
            out += sub.stdout.read()
            pprint(out.replace('\r', '\n').splitlines())
            # While it was running...
            self.assertIn('1 job running', out)


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


class OtherCommandSmokeTest(TestCase):
    """
    Smoke test a couple less-frequently used options
        --get-all-logs

    Following are not (yet) tested
        --dot
        --png
        --svg
        --debug
        --isolate
    """
    @staticmethod
    def testSmoke():
        with testEnv():
            # --get-all-logs
            jobf('true')
            jobf('--get-all-logs')


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

    def test(self):
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
            # -v
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

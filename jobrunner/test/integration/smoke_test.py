from __future__ import absolute_import, division, print_function

from logging import getLogger
import os
import re
from subprocess import CalledProcessError, check_call
from tempfile import NamedTemporaryFile
import time
from unittest import TestCase

from pexpect import EOF
import simplejson as json
import six

from jobrunner.utils import autoDecode

from .integration_lib import (
    activeJobs,
    inactiveCount,
    job,
    jobf,
    lastKey,
    noJobs,
    run,
    setUpModuleHelper,
    spawn,
    testEnv,
    waitFor,
)

LOG = getLogger(__name__)


def setUpModule():
    setUpModuleHelper()


def awaitFile(fileName, exitCode):
    return ['./await_file.py', fileName, str(exitCode)]


def unicodeCase():
    # unicode smoke test
    lineChar = '\xe2\x94\x80'
    check_call(['job', '-f', 'sh', '-c', 'echo ' + lineChar])
    check_call(['job', '--remind', 'foo ' + lineChar])
    check_call(['job', '-L'])
    check_call(['job', 'a'])
    check_call(['job', '--done', 'foo'])


def testUnicodeSmoke(capsys):
    with testEnv():
        with capsys.disabled():
            unicodeCase()


def testUnicodeSmoke2():
    with testEnv():
        unicodeCase()


class SmokeTest(TestCase):
    def testBasic(self):
        with testEnv() as env:
            waitFile1 = env.path('waitFile1')
            waitFile2 = env.path('waitFile2')
            print(run(['job'] + awaitFile(waitFile1, 1)))
            print(run(['job'] + awaitFile(waitFile2, 0)))
            print(run(['job', '-B.', 'true']))
            print(run(['job', '-B.', 'false']))
            notFound = env.path('canaryNotFound')
            run(['job', '-B.', '-c', 'touch {}'.format(notFound)])
            found = env.path('canaryFound')
            touchFound = 'touch {}'.format(found)
            run(['job', '-c', touchFound, '-b', 'waitFile1', '-B', 'waitFile2', ])
            waitFor(lambda: touchFound in activeJobs(), failArg=False)
            time.sleep(1)
            print("write wait file 1")
            open(waitFile1, 'w').write('')
            print("write wait file 2")
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
        --monitor
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
        --input
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
            out = jobf('-ll')
            self.assertIn('Reminder: do something', out)
            out = jobf('-l')
            self.assertNotIn('Reminder: do something', out)
            jobf('--done', 'something')
            out = jobf('-ll')
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

            # --delete
            # --stop
            with self.assertRaises(CalledProcessError) as error:
                jobf('--stop', 'explicitTrue')
            self.assertIn('Jobs not active:', autoDecode(error.exception.output))

            jobf('--delete', 'explicitTrue')
            with self.assertRaises(CalledProcessError) as error:
                jobf('--show', 'explicitTrue')
                self.assertIn('No job for key', autoDecode(error.exception.output))

            # --auto-job
            # --debugLocking
            out = jobf('--auto-job', '--debugLocking', 'true')
            print(out)

            with NamedTemporaryFile() as inFile:
                data = 'this is the input\n'
                inFile.write(data.encode('utf-8'))
                inFile.flush()
                # --input
                jobf('--input', inFile.name, '--', 'cat')
            catOutFile = jobf('-g', 'cat').strip()
            outData = open(catOutFile).read()
            assert data == outData

    def testWatchWait(self):
        with testEnv():
            # --watch
            # --wait
            print('+ job --watch')
            child = spawn(['job', '--watch'])
            child.expect('No jobs running')
            child.expect(r'\r')
            sleeper = spawn(['job', '--foreground', 'sleep', '60'])
            sleeper.expect(r'execute: sleep 60')

            # Confirm --watch output
            child.expect(r'1 job running')
            child.sendintr()

            # Wait for the sleep 60
            waiter = spawn(['job', '--wait', 'sleep'])
            waiter.expect(r'adding dependency.*sleep 60')

            # Kill the sleep 60
            sleeper.sendintr()
            waiter.expect(r'Dependent job failed:.*sleep 60')
            waiter.expect(EOF)

    def testRobot(self):
        with testEnv():
            out = jobf('--robot-format', 'true')
            sep = '\x00'
            matchOut = r"""
            new{sep}key=(\S*_true)\n               # job added to DB
            execute{sep}key=\1{sep}command=true\n  # actual job execution
            finish{sep}key=\1{sep}rc=0\n           # job finishes
            """
            reg = re.compile(matchOut.format(sep=sep),
                             re.MULTILINE | re.VERBOSE)
            six.assertRegex(self, out, reg)

    def testMonitor(self):
        # --monitor
        with testEnv():
            child = spawn(['job', '--monitor', '-c', 'echo MARKOUTPUT'])
            child.expect(r'\sMARKOUTPUT\s')
            child.sendintr()


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
            with NamedTemporaryFile() as rcFile:
                rcFile.write(MAIL_CONFIG.encode('utf-8'))
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
        # pylint: disable=too-many-locals
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
            progEchoRe = re.compile(r'^Command \s*echo second$', re.M)
            six.assertRegex(self, listInactiveVerbose, progEchoRe)
            # -vvv
            subEnv = dict(os.environ)
            subEnv.update({'INACTIVE_EXTRA_VERBOSE': '0123\x07123\n'})
            jobf('echo', 'second', env=subEnv)
            listInactiveExtraVerbose = job(
                '-s', 'echo second', '-vvv', env=subEnv)
            LOG.debug('listInactiveExtraVerbose %s', listInactiveExtraVerbose)
            self.assertIn(
                'INACTIVE_EXTRA_VERBOSE=0123\\x07123\\x0a',
                listInactiveExtraVerbose)

            # --show
            six.assertRegex(self, job('--show', secondKey), progEchoRe)
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

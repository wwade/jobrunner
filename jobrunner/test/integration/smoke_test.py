import json
from json import load
from logging import getLogger
import os
import re
from shlex import quote
from subprocess import CalledProcessError, check_call
from tempfile import NamedTemporaryFile
import time
from unittest import TestCase

from pexpect import EOF
import pytest
import six

from jobrunner.utils import autoDecode

from ...compat import encoding_open
from .integration_lib import (
    activeJobs,
    getTestEnv,
    inactiveCount,
    job,
    jobf,
    lastKey,
    noJobs,
    run,
    setUpModuleHelper,
    spawn,
    waitFor,
)

LOG = getLogger(__name__)


def setUpModule():
    setUpModuleHelper()


def awaitFile(fileName, exitCode):
    return ["./await_file.py", fileName, str(exitCode)]


def unicodeCase():
    # unicode smoke test
    lineChar = "\xe2\x94\x80"
    check_call(["job", "-f", "sh", "-c", "echo " + lineChar])
    check_call(["job", "--remind", "foo " + lineChar])
    check_call(["job", "-L"])
    check_call(["job", "a"])
    check_call(["job", "--done", "foo"])


def testUnicodeSmoke(capsys):
    with getTestEnv():
        with capsys.disabled():
            unicodeCase()


def testUnicodeSmoke2():
    with getTestEnv():
        unicodeCase()


@pytest.mark.parametrize(
    "cmd,expected",
    [
        (["job"], r"^Error: Job database is empty$"),
        (["job", "-g", "."], r"^Error: No job for key .\..$"),
        (["job", "-g", "xxx"], r"^Error: No job for key .xxx.$"),
    ],
)
def testEmptyDb(cmd, expected):
    with getTestEnv():
        with pytest.raises(CalledProcessError) as error:
            run(cmd, capture=True)
        output = autoDecode(error.value.output)
        print(output)
        assert re.match(expected, output)


class SmokeTest(TestCase):
    def testBasic(self):
        with getTestEnv() as env:
            waitFile1 = env.path("waitFile1")
            waitFile2 = env.path("waitFile2")
            print(run(["job"] + awaitFile(waitFile1, 1)))
            print(run(["job"] + awaitFile(waitFile2, 0)))
            print(run(["job", "-B.", "true"]))
            print(run(["job", "-B.", "false"]))
            notFound = env.path("canaryNotFound")
            run(["job", "-B.", "-c", "touch {}".format(notFound)])
            found = env.path("canaryFound")
            touchFound = "touch {}".format(found)
            run(
                [
                    "job",
                    "-c",
                    touchFound,
                    "-b",
                    "waitFile1",
                    "-B",
                    "waitFile2",
                ]
            )
            waitFor(lambda: touchFound in activeJobs(), failArg=False)
            time.sleep(1)
            print("write wait file 1")
            encoding_open(waitFile1, "w").write("")
            print("write wait file 2")
            encoding_open(waitFile2, "w").write("")
            waitFor(noJobs)
            print(run(["job", "-L"], capture=True))
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
        with getTestEnv() as env:
            os.environ["TMUX_PANE"] = "pane1"
            # --quiet
            # --foreground
            out = jobf("--quiet", "true")
            self.assertEqual(out, "")

            # --command
            out = jobf("--command", "false || true")
            self.assertIn("return code: 0", out)

            # --retry
            out = jobf("--retry", "||")
            self.assertIn("false || true", out)
            self.assertIn("return code: 0", out)

            # --reminder
            # --done
            jobf("--reminder", "do something")
            out = jobf("-ll")
            self.assertIn("Reminder: do something", out)
            out = jobf("-l")
            self.assertNotIn("Reminder: do something", out)
            jobf("--done", "something")
            out = jobf("-ll")
            self.assertNotIn("Reminder: do something", out)

            # --key
            jobf("--key", "explicitTrue", "true")
            self.assertEqual("explicitTrue", lastKey())

            # --state-dir
            newStateDir = env.path("newStateDir")
            jobf("--state-dir", newStateDir, "true")
            out = jobf("--state-dir", newStateDir, "--count")
            self.assertEqual(int(out), 1)

            # --tw
            out = jobf("--tw", "-L")
            # Without a workspaceIdentity plugin, all workspaces should match.
            self.assertIn("[explicitTrue]", out)

            # --tp
            os.environ["TMUX_PANE"] = "pane2"
            out = jobf("--tp", "-L")
            self.assertIn("(None)", out)

            # --blocked-by
            # --blocked-by-success
            # See SmokeTest

            # --delete
            # --stop
            with self.assertRaises(CalledProcessError) as error:
                jobf("--stop", "explicitTrue")
            self.assertIn("Jobs not active:", autoDecode(error.exception.output))

            jobf("--delete", "explicitTrue")
            with self.assertRaises(CalledProcessError) as error:
                jobf("--show", "explicitTrue")
                self.assertIn("No job for key", autoDecode(error.exception.output))

            # --auto-job
            # --debugLocking
            out = jobf("--auto-job", "--debugLocking", "true")
            print(out)

            with NamedTemporaryFile() as inFile:
                data = "this is the input\n"
                inFile.write(data.encode("utf-8"))
                inFile.flush()
                # --input
                jobf("--input", inFile.name, "--", "cat")
            catOutFile = jobf("-g", "cat").strip()
            outData = encoding_open(catOutFile).read()
            assert data == outData

    def testWatchWait(self):
        with getTestEnv():
            # --watch
            # --notifier
            # --wait
            print("+ job --watch")
            watch = spawn(["job", "--watch"])
            watch.expect("No jobs running")
            watch.expect(r"\r")

            with NamedTemporaryFile() as notifierOut:
                notifierOut.close()
                env = dict(os.environ)
                env["DUMP_FILE"] = notifierOut.name
                cmd = ["job", "--notifier", "./dump_json_input.py"]
                print("+", map(quote, cmd))
                notifier = spawn(cmd, env=env)

                sleeper = spawn(["job", "--foreground", "sleep", "60"])
                sleeper.expect(r"] \+ sleep 60")

                # Confirm --watch output
                watch.expect(r"1 job running")
                watch.sendintr()

                # Wait for the sleep 60
                waiter = spawn(["job", "--wait", "sleep"])
                waiter.expect(r"adding dependency.*sleep 60")

                # CRITICAL: Give the notifier time to poll and see the job is active.
                # The notifier polls every 1 second. If we kill the job before the
                # notifier's first poll includes it in curJobs, the notification will
                # never be sent (the job won't be in "curJobs - activeJobs"). Sleep
                # for 1.5 seconds to ensure the notifier has polled at least once and
                # captured the sleep job in its active jobs list.
                time.sleep(1.5)

                # Kill the sleep 60
                sleeper.sendintr()
                waiter.expect(r"dependent job failed:.*sleep 60")
                waiter.expect(EOF)

                notifier.expect("dumped")
                notifier.sendintr()
                notifier.expect(EOF)
                notifierOut.close()

                with open(notifierOut.name, encoding="utf-8") as fp:
                    dumped = load(fp)
                    print(dumped)
                    self.assertIn("subject", dumped)
                    self.assertIn("body", dumped)
                    self.assertIn("rc", dumped)
                    self.assertEqual(-1, dumped["rc"])
                    self.assertRegex(dumped["subject"], r"^Job finished.*sleep 60$")

    def testRobot(self):
        with getTestEnv():
            out = jobf("--robot-format", "true")
            sep = "\x00"
            matchOut = r"""
            new{sep}key=(\S*_true)\n               # job added to DB
            execute{sep}key=\1{sep}command=true\n  # actual job execution
            finish{sep}key=\1{sep}rc=0\n           # job finishes
            """
            reg = re.compile(matchOut.format(sep=sep), re.MULTILINE | re.VERBOSE)
            six.assertRegex(self, out, reg)

    def testMonitor(self):
        # --monitor
        with getTestEnv():
            child = spawn(["job", "--monitor", "-c", "echo MARKOUTPUT"])
            child.expect(r"\sMARKOUTPUT\s")
            child.sendintr()

    def testOutputFormat(self):
        """Test that job output has consistent [key] prefix format."""
        with getTestEnv():
            # Test successful job output format
            out = jobf("true")
            # Verify key prefix and command format: [<key>] + <command>
            six.assertRegex(self, out, r"(?m)^\[\d+_true\] \+ true$")
            # Verify key prefix and return code format: [<key>] return code: <rc>
            six.assertRegex(self, out, r"(?m)^\[\d+_true\] return code: 0$")

            # Test failed job output format
            try:
                jobf("false")
                self.fail("Expected CalledProcessError")
            except CalledProcessError as error:
                out = autoDecode(error.output)
                six.assertRegex(self, out, r"(?m)^\[\d+_false\] \+ false$")
                six.assertRegex(self, out, r"(?m)^\[\d+_false\] return code: 1$")

            # Test dependency failure message format
            try:
                jobf("false")
            except CalledProcessError:
                pass
            failKey = lastKey()
            try:
                jobf("-B", failKey, "true")
                self.fail("Expected CalledProcessError")
            except CalledProcessError as error:
                out = autoDecode(error.output)
                # Should have key prefix (of the waiting job) for failure message
                # Format: [{waiting_job_key}] dependent job failed: ...
                # [{failed_job_key}] {cmd}
                six.assertRegex(
                    self,
                    out,
                    r"(?m)^\[\d+_true\] dependent job failed:.*\["
                    + re.escape(failKey)
                    + r"\].*false",
                )


MAIL_CONFIG = """
[mail]
program=./send_email.py
domain=example.com
"""


class RunMailTest(TestCase):
    """
    Test mail-related options

        --mail
        --notify
        --to
        --cc
        --rc-file
    """

    @staticmethod
    def getMailArgs(mailKey):
        lastLog = job("-g", mailKey).splitlines()[0]
        return json.load(encoding_open(lastLog))

    def test(self):
        with getTestEnv():
            with NamedTemporaryFile() as rcFile:
                rcFile.write(MAIL_CONFIG.encode("utf-8"))
                rcFile.flush()
                # --mail
                # --rc-file
                jobf("true")
                jobf("--rc-file", rcFile.name, "--mail", ".")
                args1 = self.getMailArgs(lastKey())
                self.assertIn("-s", args1)
                self.assertIn("-a", args1)
                self.assertIn("me", args1)
                # --to
                # --cc
                jobf(
                    "--rc-file",
                    rcFile.name,
                    "--mail",
                    "true",
                    "--to",
                    "someone",
                    "--cc",
                    "another",
                )
                args2 = self.getMailArgs(lastKey())
                print(repr(args2))
                self.assertIn("-s", args2)
                self.assertIn("-a", args2)
                self.assertNotIn("me", args2)
                self.assertIn("someone", args2)
                self.assertIn("another@example.com", args2)

    def testNotify(self):
        with getTestEnv():
            with NamedTemporaryFile() as rcFile:
                rcFile.write(MAIL_CONFIG.encode("utf-8"))
                rcFile.flush()
                with NamedTemporaryFile() as dumpFile:
                    os.environ["SEND_EMAIL_DUMP_FILE"] = dumpFile.name
                    # --notify
                    jobf("--rc-file", rcFile.name, "--notify", "true")
                    with open(dumpFile.name, "r", encoding="utf-8") as fp:
                        args = json.load(fp)
                    self.assertIn("-s", args)
                    self.assertIn("-a", args)
                    self.assertIn("me", args)


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
        with getTestEnv():
            # --get-all-logs
            jobf("true")
            jobf("--get-all-logs")


class RunFindTest(TestCase):
    """
    Test the --find option for searching jobs by keyword.
    """

    def test(self):
        with getTestEnv():
            # Create test jobs with different patterns
            jobf("echo", "find_test_1")
            jobf("echo", "find_test_2")
            jobf("echo", "other_command")

            # Test basic find by command keyword
            findOutput = job("--find", "find_test")
            self.assertIn("find_test_1", findOutput)
            self.assertIn("find_test_2", findOutput)
            self.assertNotIn("other_command", findOutput)

            # Test finding by key prefix
            key3 = lastKey()
            keyPrefix = key3[:10]
            findByKey = job("--find", keyPrefix)
            self.assertIn(key3, findByKey)

            # Test with verbose output
            findVerbose = job("-v", "--find", "find_test")
            self.assertIn("Command", findVerbose)
            self.assertIn("echo find_test", findVerbose)

            # Test with no matches
            findEmpty = job("--find", "nonexistent_pattern_xyz")
            self.assertIn("No jobs matching", findEmpty)

            # Test with --tw (this workspace) filter
            findTw = job("--tw", "--find", "find_test")
            # Should still find jobs since we're in the same workspace
            self.assertIn("find_test", findTw)

            # Test multiple --find arguments
            jobf("echo", "pattern_a")
            jobf("echo", "pattern_b")
            multiFind = job("--find", "pattern_a", "--find", "pattern_b")
            self.assertIn("pattern_a", multiFind)
            self.assertIn("pattern_b", multiFind)

            # Test with checkpoint filtering
            # Create jobs before checkpoint
            jobf("echo", "before_checkpoint_1")
            jobf("echo", "before_checkpoint_2")
            # Set checkpoint
            job("--set-checkpoint", ".")
            # Create jobs after checkpoint
            jobf("echo", "after_checkpoint_1")
            jobf("echo", "after_checkpoint_2")

            # Find without checkpoint - should find all
            allMatches = job("--find", "checkpoint")
            self.assertIn("before_checkpoint_1", allMatches)
            self.assertIn("before_checkpoint_2", allMatches)
            self.assertIn("after_checkpoint_1", allMatches)
            self.assertIn("after_checkpoint_2", allMatches)

            # Find with checkpoint - should only find jobs after checkpoint
            afterMatches = job("-p", "--find", "checkpoint")
            self.assertNotIn("before_checkpoint_1", afterMatches)
            self.assertNotIn("before_checkpoint_2", afterMatches)
            self.assertIn("after_checkpoint_1", afterMatches)
            self.assertIn("after_checkpoint_2", afterMatches)


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
        with getTestEnv():
            # --last-key
            jobf("-v", "echo", "first")
            firstKey = lastKey()
            jobf("echo", "second")
            secondKey = lastKey()
            self.assertNotEqual(firstKey, secondKey)

            # --help
            self.assertIn("Job runner with logging", job("--help"))

            # --count
            self.assertEqual(int(job("--count")), 2)

            # --list
            self.assertEqual("(None)", job("--list").strip())

            # --index
            # --get-log
            [file1] = job("--index", "1").splitlines()
            [firstLog] = job("--get-log", firstKey).splitlines()
            self.assertEqual(file1, firstLog)
            [file2] = job("--index", "0").splitlines()
            for fileName, value in ((file1, "first"), (file2, "second")):
                self.assertIn(value, encoding_open(fileName, "r").read())
            multiLogFiles = job("-g", firstKey, "-g", secondKey).split()
            self.assertEqual(len(multiLogFiles), 2)
            self.assertNotEqual(multiLogFiles[0], multiLogFiles[1])

            # --list-inactive
            # -v
            listInactive = job("--list-inactive")
            self.assertIn("echo first", listInactive)
            self.assertIn("echo second", listInactive)
            listInactiveVerbose = job("--list-inactive", "-v")
            progEchoRe = re.compile(r"^Command \s*echo second$", re.M)
            six.assertRegex(self, listInactiveVerbose, progEchoRe)
            # -vvv
            subEnv = dict(os.environ)
            subEnv.update({"INACTIVE_EXTRA_VERBOSE": "0123\x07123\n"})
            jobf("echo", "second", env=subEnv)
            listInactiveExtraVerbose = job("-s", "echo second", "-vvv", env=subEnv)
            LOG.debug("listInactiveExtraVerbose %s", listInactiveExtraVerbose)
            self.assertIn(
                "INACTIVE_EXTRA_VERBOSE=0123\\x07123\\x0a", listInactiveExtraVerbose
            )

            # --show
            six.assertRegex(self, job("--show", secondKey), progEchoRe)
            # --info
            jobInfo = job("--info")
            assert isinstance(jobInfo, str)
            self.assertRegex(jobInfo, r"DB \d+ 'active' ver \d+")
            self.assertRegex(jobInfo, r"DB \d+ 'inactive' ver \d+")

            #  --set-checkpoint
            job("--set-checkpoint", ".")
            # --since-checkpoint
            self.assertIn("(None)", job("--since-checkpoint", "--list-inactive"))

            # --prune-except
            job("--prune-except", "1")
            jobList = job("--list-inactive").splitlines()
            self.assertEqual(jobList, [jobList[0]])

            # --prune
            oldList = job("--list-inactive").splitlines()
            job("--prune").splitlines()
            newList = job("--list-inactive").splitlines()
            self.assertEqual(oldList, newList)

            # --activity
            # --activity-window

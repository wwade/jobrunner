from __future__ import absolute_import, division, print_function

import logging
from subprocess import CalledProcessError, check_output
import sys
from unittest import TestCase

from pytest import mark

from jobrunner.utils import autoDecode

from .integration_lib import (
    job,
    jobf,
    noJobs,
    run,
    runningJob,
    setUpModuleHelper,
    testEnv,
    waitFor,
)

LOG = logging.getLogger(__name__)

if sys.version_info.major < 3:
    class FileNotFoundError(Exception):  # pylint: disable=redefined-builtin
        pass


class _Module(object):
    sudoOk = 0

    def __init__(self):
        try:
            out = autoDecode(check_output(['sudo', 'python', '-V']))
        except (CalledProcessError, FileNotFoundError, OSError):
            LOG.warning("sudo check error", exc_info=True)
            return
        LOG.debug("sudo check output: %s", out)
        self.sudoOk = not out.strip()


_MODULE = _Module()


def setUpModule():
    setUpModuleHelper()


class TestInterrupt(TestCase):
    def testAsUser(self):
        with testEnv():
            # --pid
            # --int
            run(['job', 'sleep', '60'])

            def _findJob(fail=False):
                return runningJob('sleep 60', fail=fail)
            waitFor(_findJob)
            out = jobf('--pid', 'sleep')
            print("pid", out)
            self.assertNotIn("b'job", out)
            self.assertIn('sleep', out)
            job('--int', 'sleep')
            try:
                job('--int', 'sleep')
            except CalledProcessError:
                pass
            waitFor(noJobs)

    @mark.skipif(_MODULE.sudoOk != 1, reason="no sudo rights")
    def testWithSudo(self):
        with testEnv():
            run(['job', 'sudo', 'sleep', '60'])

            def _findJob(fail=False):
                return runningJob('sleep 60', fail=fail)
            waitFor(_findJob)
            job('--int', 'sleep')
            try:
                job('--int', 'sleep')
            except CalledProcessError:
                pass
            waitFor(noJobs)

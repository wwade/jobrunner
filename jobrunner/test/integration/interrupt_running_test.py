from __future__ import absolute_import, division, print_function

from subprocess import CalledProcessError, check_output
import sys
from unittest import TestCase

from pytest import mark

from .integration_lib import (
    IntegrationTestTimeout,
    job,
    jobf,
    noJobs,
    run,
    runningJob,
    setUpModuleHelper,
    testEnv,
    waitFor,
)

if sys.version_info.major < 3:
    noSudo = (CalledProcessError,)
else:
    noSudo = (CalledProcessError, FileNotFoundError)


class _Module(object):
    sudoOk = 0

    def __init__(self):
        try:
            out = check_output(['sudo', 'true'])
        except noSudo as error:
            print("Ignore sudo check error", error)
            return
        for line in out.splitlines():
            if line.endswith(' ALL') and ' NOPASSWD:' in line:
                self.sudoOk = 1
                break


_MODULE = _Module()


def setUpModule():
    setUpModuleHelper()


class TestInterrupt(TestCase):
    @mark.xfail(raises=IntegrationTestTimeout)
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
            self.assertIn('sleep', out)
            job('--int', 'sleep')
            try:
                job('--int', 'sleep')
            except CalledProcessError:
                pass
            waitFor(noJobs)

    @mark.xfail(raises=IntegrationTestTimeout)
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

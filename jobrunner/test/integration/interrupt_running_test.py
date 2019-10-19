from __future__ import absolute_import, division, print_function

from subprocess import CalledProcessError
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

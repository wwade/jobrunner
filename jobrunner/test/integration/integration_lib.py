from __future__ import absolute_import, division, print_function

from contextlib import contextmanager
import logging
import os
from pipes import quote
import re
from shutil import rmtree
from subprocess import STDOUT, CalledProcessError, check_call, check_output
from tempfile import mkdtemp
import time

import pexpect
from six.moves import map

from jobrunner.utils import autoDecode

from ..helpers import resetEnv

HOSTNAME = 'host.example.com'
HOME = '/home/me'

EXAMPLE_RCFILE = """\
[mail]
program=mail-program
domain=ex.com
"""

LOG = logging.getLogger(__name__)


class IntegrationTestTimeout(Exception):
    pass


def setUpModuleHelper():
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
        rmtree(tmpDir, ignore_errors=True)
        os.environ['JOBRUNNER_STATE_DIR'] = '/tmp/BADDIR'


def run(cmd, capture=False, env=None):
    print(' '.join(map(quote, cmd)))
    try:
        if capture:
            out = autoDecode(check_output(cmd, stderr=STDOUT, env=env))
            LOG.debug("cmd %r => %s", cmd, out.strip())
            return out
        else:
            return check_call(cmd, env=env)
    except CalledProcessError as error:
        print(error.output)
        LOG.debug("cmd %r => ERROR %s", cmd, autoDecode(error.output).strip())
        raise


def jobf(*cmd, **kwargs):
    jobCmd = ['job', '--foreground'] + list(cmd)
    return run(jobCmd, capture=True, **kwargs)


def job(*cmd, **kwargs):
    jobCmd = ['job'] + list(cmd)
    return run(jobCmd, capture=True, **kwargs)


def waitFor(func, timeout=60.0, failArg=True):
    interval = [0] * 3 + [0.1] * 10 + [0.25] * 10
    elapsed = 0
    while elapsed <= timeout:
        startTime = time.time()
        if func():
            return
        endTime = time.time()
        if endTime > startTime:
            elapsed += endTime - startTime
        if interval:
            sleepTime = interval.pop(0)
        else:
            sleepTime = 1
        elapsed += sleepTime
        time.sleep(sleepTime)
    if failArg:
        print('elapsed', elapsed)
        func(fail=True)
    raise IntegrationTestTimeout('timed out waiting for %r' % func)


def activeJobs():
    return run(['job', '-l'], capture=True)


def runningJob(name, fail=False):
    out = run(['job', '-s', name], capture=True)
    LOG.debug("runningJob(%r) => %s", name, out.strip())
    reg1 = re.compile(r'\nState\s+Running\n')
    reg2 = re.compile(r'\nDuration\s+Blocked\n')
    pid = re.compile(r'\nPID\s+(\d+)\n')
    running = reg1.search(out)
    blocked = reg2.search(out)
    pidMatch = pid.search(out)
    if fail:
        print(out)
    return running and pidMatch and not blocked


def noJobs(fail=False):
    jobs = activeJobs()
    if fail:
        print(jobs)
    return jobs.splitlines()[0] == '(None)'


def lastKey():
    [ret] = run(['job', '-K'], capture=True).splitlines()
    return ret


def inactiveCount():
    return int(run(['job', '--count'], capture=True))


def spawn(cmd):
    print(" ".join(map(quote, cmd)))
    child = pexpect.spawn(cmd[0], cmd[1:], echo=True)
    return child

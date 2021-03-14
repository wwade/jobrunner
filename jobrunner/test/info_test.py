from __future__ import absolute_import, division, print_function

from logging import getLogger
import os
import unittest

import mock
import simplejson as json
import six

from jobrunner import db, info, plugins, utils
from jobrunner.service.registry import registerServices

from .helpers import resetEnv

LOG = getLogger(__name__)


def setUpModule():
    resetEnv()
    registerServices(testing=True)
    os.environ['HOSTNAME'] = 'testHostname'
    os.environ['USER'] = 'somebody'
    if 'WP' in os.environ:
        del os.environ['WP']


def setJobEnv(jobInfo, newEnv):
    # pylint: disable=protected-access
    jobInfo._env = newEnv


def newJob(uidx, cmd, workspaceIdentity="WS"):
    mockPlug = mock.MagicMock(plugins.Plugins)
    mockPlug.workspaceIdentity.return_value = workspaceIdentity
    utils.MOD_STATE.plugins = mockPlug
    parent = mock.MagicMock(db.JobsBase)
    parent.inactive = mock.MagicMock(db.DatabaseBase)
    parent.active = mock.MagicMock(db.DatabaseBase)
    jobInfo = info.JobInfo(uidx)
    jobInfo.isolate = False
    jobInfo.setCmd(cmd)
    jobInfo.parent = parent
    setJobEnv(jobInfo, {'NOENV': '1'})
    return jobInfo


class TestJobInfoJson(unittest.TestCase):
    def cmpObj(self, objA, objB):
        print(objA.detail(3 * ['v']))
        print(objB.detail(3 * ['v']))
        six.assertCountEqual(self, list(objA.__dict__.keys()),
                             list(objA.__dict__.keys()))
        for key in objA.__dict__:
            if key == '_parent':
                continue
            self.assertDictEqual({key: objA.__dict__[key]},
                                 {key: objB.__dict__[key]})

    def testStarted(self):
        job = newJob(12, ['ls', '/tmp'])
        job.start(job.parent)
        jsonRepr = json.dumps(job, default=info.encodeJobInfo)
        jobOut = json.loads(jsonRepr, object_hook=info.decodeJobInfo)
        self.cmpObj(job, jobOut)

    def testStopped(self):
        job = newJob(13, ['ls', '/tmp'])
        job.start(job.parent)
        job.stop(job.parent, 1)
        jsonRepr = json.dumps(job, default=info.encodeJobInfo)
        jobOut = json.loads(jsonRepr, object_hook=info.decodeJobInfo)
        self.cmpObj(job, jobOut)


class TestReminder(unittest.TestCase):
    def testInfo(self):
        job = newJob(14, ['(reminder)'])
        job.start(job.parent)
        job.reminder = 'This is a reminder'
        outDetail1 = job.detail(["v", "v", "v"])
        out1 = job.detail([])
        print(out1)
        self.assertEqual(outDetail1, out1)
        six.assertRegex(self, out1, r"\nReminder\s+This is a reminder\n")
        self.assertNotIn("\nState ", out1)
        job.stop(job.parent, utils.STOP_DONE)
        out2 = job.detail("vvv")
        six.assertRegex(self, out2, r"\nReminder\s+This is a reminder\n")
        six.assertRegex(self,
                        out2, r"\nState\s+Finished \(Completed Reminder\)\n")
        print(out2)


class TestJobProperties(unittest.TestCase):
    def testEnv(self):
        job = newJob(14, ['ls', '/tmp'])
        job.start(job.parent)
        env = {'XY': u'1', 'VAL_WITH_NEWLINE': 'first\nsecond'}
        setJobEnv(job, env)
        out = job.getEnvironment()
        self.assertIn("XY=1\n", out)
        self.assertIn("VAL_WITH_NEWLINE=first\\x0asecond", out)
        self.assertEqual(job.env('XY'), '1')
        self.assertIsNone(job.env('XYZ'))
        self.assertEqual(job.environ, env)
        self.assertTrue(job.matchEnv('XY', '1'))
        self.assertFalse(job.matchEnv('XY', '0'))

    def testWorkspaceInfo(self):
        job = newJob(14, 'true')
        job.start(job.parent)
        self.assertEqual(job.wsBasename(), "WS")
        self.assertEqual(job.workspace, "WS")

    def testWorkspaceInfoNoPlugin(self):
        job = newJob(14, 'true', workspaceIdentity="")
        job.start(job.parent)
        self.assertEqual(job.wsBasename(), "")
        self.assertEqual(job.workspace, "")


class TestInfoHelpers(unittest.TestCase):
    def _assertCmd(self, actual, expected):
        actual.encode('ascii')
        self.assertEqual(actual, expected)

    def testCmdString(self):
        cmd = ['ls', '-l', 'some file']
        self._assertCmd(info.cmdString(cmd), "ls -l 'some file'")
        cmd = ['ls', '-l', 'some\tfile']
        self._assertCmd(info.cmdString(cmd), "ls -l 'some\tfile'")
        cmd = [u'ls', u'-l', u'some\tfile']
        self._assertCmd(info.cmdString(cmd), "ls -l 'some\tfile'")
        cmd = ['ls', '-l', 'some;file']
        self._assertCmd(info.cmdString(cmd), "ls -l 'some;file'")

    def testCmdStringBang(self):
        cmd = [u'ls', u'-l', u'!something']
        self._assertCmd(info.cmdString(cmd), "ls -l '!something'")

    def testCmdStringEncodingError(self):
        cmd = [u'foo', u'bar\xa0', u'zoo']
        self._assertCmd(info.cmdString(cmd), "foo 'bar<A0>' zoo")

    def testEscEncUnicode(self):
        value = u'abc'
        exp = 'abc'
        out = info.JobInfo.escEnv(value)
        assert exp == out

    def testEscEnv(self):
        value = '12\x00\x01\n'
        exp = '12\\x00\\x01\\x0a'
        out = info.JobInfo.escEnv(value)
        LOG.debug('exp [%r] %s', exp, exp)
        LOG.debug('out [%r] %s', out, out)
        assert exp == out

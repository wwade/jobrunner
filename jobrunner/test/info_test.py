from __future__ import absolute_import, division, print_function

import os
import unittest

import mock
import simplejson as json

from jobrunner import db, info, plugins, utils

from .helpers import resetEnv


def setUpModule():
    resetEnv()
    os.environ['HOSTNAME'] = 'testHostname'
    os.environ['USER'] = 'somebody'
    if 'WP' in os.environ:
        del os.environ['WP']


class TestJobInfoJson(unittest.TestCase):
    @staticmethod
    def newJob(uidx, cmd):
        mockPlug = mock.MagicMock(plugins.Plugins)
        mockPlug.workspaceIdentity.return_value = "WS"
        utils.MOD_STATE.plugins = mockPlug
        parent = mock.MagicMock(db.Jobs)
        parent.inactive = mock.MagicMock(db.Database)
        parent.active = mock.MagicMock(db.Database)
        jobInfo = info.JobInfo(uidx)
        jobInfo.isolate = False
        jobInfo.setCmd(cmd)
        jobInfo.parent = parent
        return jobInfo

    def cmpObj(self, objA, objB):
        print(objA.detail(3 * ['v']))
        print(objB.detail(3 * ['v']))
        self.assertItemsEqual(objA.__dict__.keys(), objA.__dict__.keys())
        for key in objA.__dict__:
            if key == '_parent':
                continue
            self.assertDictEqual({key: objA.__dict__[key]},
                                 {key: objB.__dict__[key]})

    def testStarted(self):
        job = self.newJob(12, ['ls', '/tmp'])
        job.start(job.parent)
        jsonRepr = json.dumps(job, default=info.encodeJobInfo)
        jobOut = json.loads(jsonRepr, object_hook=info.decodeJobInfo)
        self.cmpObj(job, jobOut)

    def testStopped(self):
        job = self.newJob(13, ['ls', '/tmp'])
        job.start(job.parent)
        job.stop(job.parent, 1)
        jsonRepr = json.dumps(job, default=info.encodeJobInfo)
        jobOut = json.loads(jsonRepr, object_hook=info.decodeJobInfo)
        self.cmpObj(job, jobOut)


class TestInfoHelpers(unittest.TestCase):
    def testCmdString(self):
        cmd = ['ls', '-l', 'some file']
        self.assertEqual(info.cmdString(cmd), "ls -l 'some file'")
        cmd = ['ls', '-l', 'some\tfile']
        self.assertEqual(info.cmdString(cmd), "ls -l 'some\tfile'")
        cmd = ['ls', '-l', 'some;file']
        self.assertEqual(info.cmdString(cmd), "ls -l 'some;file'")

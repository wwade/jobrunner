from __future__ import absolute_import, division, print_function

from datetime import datetime
import unittest

from dateutil.tz import tzlocal, tzutc
from mock import MagicMock, patch

from jobrunner.db.dbm_db import DatabaseBase, DbmDatabase, JobsBase
from jobrunner.info import JobInfo
from jobrunner.service import service

from .helpers import resetEnv

LOCAL = tzlocal()
UTC = tzutc()


def setUpModule():
    resetEnv()


class BaseMixin(object):
    def _initMocks(self, *args):
        self.myDict = {}  # pylint: disable=attribute-defined-outside-init
        initMock = args[-2]
        openDb = args[-1]
        openDb.return_value = self.myDict
        initMock.return_value = None
        testObj = DbmDatabase(None, None, None, "xxx")
        return testObj


@patch("jobrunner.db.dbm_db.DbmDatabase._openDb")
@patch("jobrunner.db.dbm_db.DbmDatabase.__init__")
@patch("jobrunner.db.utcNow")
class DatabasePropertiesCheckpointTest(BaseMixin, unittest.TestCase):
    def testCheckpointUnset(self, *args):
        """
        testCheckpointUnset - No checkpoint set, should return epoch
        """
        testObj = self._initMocks(*args)
        checkpoint = testObj.checkpoint
        self.assertEqual(checkpoint.tzinfo, UTC)
        self.assertEqual(checkpoint.astimezone(LOCAL).strftime("%s"), "0")

    def testCheckpointNow(self, nowPatch, *args):
        """
        testCheckpointNow - Set with "." and return now (UTC)
        """
        testObj = self._initMocks(*args)
        fakeNow = datetime(2000, 3, 4, 16, 20, 00, tzinfo=UTC)
        nowPatch.return_value = fakeNow
        testObj.setCheckpoint(".")
        testNow = testObj.checkpoint
        self.assertEqual(testNow, fakeNow)

    def testCheckpointFromStr(self, nowPatch, *args):
        testObj = self._initMocks(*args)
        myTime = '2010-12-31 3pm'
        myTimeObj = datetime(2010, 12, 31, 15, tzinfo=LOCAL)
        testObj.setCheckpoint(myTime)
        checkVal = testObj.getCheckpoint()
        self.assertEqual(checkVal, myTimeObj)
        nowPatch.assert_not_called()

    def testCheckpointNoTz(self, nowPatch, *args):
        """
        testCheckpointNoTz - Set with explicit value, no tzinfo (use local)
        """
        testObj = self._initMocks(*args)
        myTime = datetime(2001, 1, 1, 13, 40, 00)
        testObj.checkpoint = myTime
        checkVal = testObj.checkpoint
        self.assertEqual(checkVal.tzinfo, UTC)
        myTimeLocal = myTime.replace(tzinfo=LOCAL)
        self.assertEqual(checkVal, myTimeLocal)
        nowPatch.assert_not_called()

    def testCheckpointWithTz(self, nowPatch, *args):
        """
        testCheckpointWithTz - Set with explicit value including tzinfo
        """
        testObj = self._initMocks(*args)
        myTime = datetime(2001, 1, 1, 13, 40, 00, tzinfo=LOCAL)
        testObj.checkpoint = myTime
        checkVal = testObj.checkpoint
        self.assertEqual(checkVal.tzinfo, UTC)
        self.assertEqual(checkVal, myTime)
        nowPatch.assert_not_called()


class Kvs(object):
    def __init__(self):
        self.kvs = {}

    def __setitem__(self, key, value):
        self.kvs[unicode(key)] = unicode(value)

    def __getitem__(self, key):
        return self.kvs[unicode(key)]

    def __delitem__(self, key):
        del self.kvs[unicode(key)]

    def __contains__(self, key):
        return unicode(key) in self.kvs

    def __len__(self):
        return len(self.kvs)

    def keys(self):
        return self.kvs.keys()


class MockDb(DatabaseBase):
    def __init__(self, parent, config):
        super(MockDb, self).__init__(parent, config, None)
        self._db = Kvs()
        for key, value in self.defaultValueGenerator("0"):
            self._db[key] = value

    def __len__(self):
        return len(self._db)

    @property
    def db(self):
        return self._db


class MockJobs(JobsBase):
    def __init__(self):
        config = MagicMock()
        config.debugLevel = []
        super(MockJobs, self).__init__(config, None)
        self.active = MockDb(self, config)
        self.inactive = MockDb(self, config)

    def isLocked(self):
        return False

    def countInactive(self):
        return len([k for k in self.inactive.keys()
                    if k not in self.inactive.special])


class MockJob(JobInfo):
    pass


@patch("tempfile.mkstemp", return_value=(None, "/tmp/fubar"))
@patch("jobrunner.info.workspaceIdentity", return_value=None)
class DatabasePruneTest(unittest.TestCase):
    def setUp(self):
        service().clear(thisIsATest=True)
        service().register("db.jobInfo", MockJob)

    def testBasic(self, _wsIdent, _mkstemp):
        jobs = MockJobs()
        jobList = []
        for _ in range(30):
            job = jobs.new(['fake', 'cmd1'], False)[0]
            job.start(jobs)
            jobList.append(job)
        jobs.prune(exceptNum=2)
        self.assertEqual(0, jobs.countInactive())

        for job in jobList:
            job.stop(jobs, 0)

        self.assertEqual(30, jobs.countInactive())
        jobs.prune(exceptNum=2)
        self.assertEqual(2, jobs.countInactive())

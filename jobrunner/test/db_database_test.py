from __future__ import absolute_import, division, print_function

from datetime import datetime
import unittest

from dateutil.tz import tzlocal, tzutc
from mock import patch

from jobrunner.db.dbm_db import DbmDatabase

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

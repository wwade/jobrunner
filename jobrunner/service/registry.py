from __future__ import absolute_import

from . import service
from ..db import JobInfo
from ..db.sqlite_db import Sqlite3Jobs


def registerServices(testing=False):
    if testing:
        service().clear(thisIsATest=testing)
    service().register("db.jobs", Sqlite3Jobs)
    service().register("db.jobInfo", JobInfo)

from . import service
from ..db import JobInfo
from ..db.dbm_db import DbmJobs
from ..db.sqlite_db import Sqlite3Jobs


def registerServices(sqlite=False, testing=False):
    if testing:
        service().clear(thisIsATest=testing)
    if sqlite:
        service().register("db.jobs", Sqlite3Jobs)
    else:
        service().register("db.jobs", DbmJobs)
    service().register("db.jobInfo", JobInfo)

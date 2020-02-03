from . import service
from ..db.dbm_db import DbmJobs
from ..db.sqlite_db import Sqlite3Jobs


def registerServices(sqlite=False):
    if sqlite:
        service().register("db.jobs", Sqlite3Jobs)
    else:
        service().register("db.jobs", DbmJobs)

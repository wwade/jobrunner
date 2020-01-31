from . import service
from ..db import Jobs
from ..db.dbm_db import DbmDatabase


def registerServices():
    service().register("db.jobs", Jobs)
    service().register("db.database", DbmDatabase)

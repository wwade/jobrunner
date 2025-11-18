from __future__ import absolute_import

from . import service
from ..db import JobInfo
from ..db.relational_db import RelationalJobs


def registerServices(testing=False):
    if testing:
        service().clear(thisIsATest=testing)
    service().register("db.jobs", RelationalJobs)
    service().register("db.jobInfo", JobInfo)

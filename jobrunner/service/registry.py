from __future__ import absolute_import

from . import service
from ..db import JobInfo
from ..db.repository_adapter import RepositoryAdapter


def registerServices(testing: bool = False) -> None:
    # pylint: disable=unused-argument
    """
    Register database services.

    Args:
        db: Database type (ignored, only repository adapter is used now)
        testing: If True, clear services for testing
    """
    if testing:
        service().clear(thisIsATest=testing)

    # Register the repository adapter as the jobs database
    service().register("db.jobs", RepositoryAdapter)

    # Register JobInfo for backward compatibility
    service().register("db.jobInfo", JobInfo)

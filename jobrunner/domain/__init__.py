"""
Domain models for jobrunner.

This package contains pure domain logic with no database coupling.
"""

from .job import Job, JobStatus

__all__ = ["Job", "JobStatus"]

"""
Adapters for bridging old and new architectures.

This package contains adapters that allow the old codebase to use
the new clean architecture (Domain/Repository/Service layers) without
requiring a complete rewrite.
"""

from .job_converter import job_to_jobinfo, jobinfo_to_job

__all__ = ["job_to_jobinfo", "jobinfo_to_job"]

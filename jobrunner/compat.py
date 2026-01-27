#!/usr/bin/env python

# pylint: disable=unused-import

from importlib import metadata
from typing import List


def get_plugins(group: str) -> List[metadata.EntryPoint]:
    eps = metadata.entry_points()
    if not hasattr(eps, "get"):
        # in 3.12+, EntryPoints.get() should be replaced by select().
        return list(eps.select(group=group))
    return list(eps.get(group, []))


def encoding_open(filename, mode="r", encoding="utf-8", **kwargs):
    return open(filename, mode=mode, encoding=encoding, **kwargs)

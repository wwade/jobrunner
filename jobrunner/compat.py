#!/usr/bin/env python

# pylint: disable=unused-import

from typing import List

try:
    from importlib import metadata
    __importlib = True
except ImportError:
    # Running on pre-3.8 Python; use importlib-metadata package
    import importlib_metadata as metadata
    __importlib = False


def get_plugins(group: str) -> List[metadata.EntryPoint]:
    eps = metadata.entry_points()
    if __importlib:
        return list(eps.get(group, []))
    return list(eps.select(group=group))


def encoding_open(filename, mode='r', encoding='utf-8', **kwargs):
    try:
        return open(filename, mode=mode, encoding=encoding, **kwargs)
    except TypeError:
        return open(filename, mode=mode, **kwargs)  # pylint: disable=W

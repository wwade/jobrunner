#!/usr/bin/env python
# Copyright (c) 2021 Arista Networks, Inc.  All rights reserved.
# Arista Networks, Inc. Confidential and Proprietary.

from __future__ import absolute_import, division, print_function

# pylint: disable=unused-import

try:
    from importlib import metadata
except ImportError:
    # Running on pre-3.8 Python; use importlib-metadata package
    import importlib_metadata as metadata


def encoding_open(filename, mode='r', encoding='utf-8', **kwargs):
    try:
        return open(filename, mode=mode, encoding=encoding, **kwargs)
    except TypeError:
        return open(filename, mode=mode, **kwargs)  # pylint: disable=W

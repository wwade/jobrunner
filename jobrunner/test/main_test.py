#!/usr/bin/env python
# Copyright (c) 2021 Arista Networks, Inc.  All rights reserved.
# Arista Networks, Inc. Confidential and Proprietary.

from __future__ import absolute_import, division, print_function

import pytest

from jobrunner.main import handleIsolate

long1 = ['long'] * 10
long2 = [u'long\u2031\x23\x33\x44'] * 10


@pytest.mark.parametrize('cmd, expected', [
    (['ls'], ['isolate', '-n', 'ls', 'ls']),
    (long1, ['isolate', '-n', '8d5d4f21f886008b'] + long1),
    (long2, ['isolate', '-n', '62c391022349f233'] + long2),
])
def testHandleIsolate(cmd, expected):
    isolated = handleIsolate(cmd)
    assert expected == isolated

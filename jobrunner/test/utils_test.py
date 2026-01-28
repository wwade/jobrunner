#!/usr/bin/env python
# Copyright (c) 2021 Arista Networks, Inc.  All rights reserved.
# Arista Networks, Inc. Confidential and Proprietary.

from __future__ import absolute_import, division, print_function

from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest

from jobrunner.utils import autoDecode, humanTimeDeltaSecs


@pytest.mark.parametrize(
    ("value", "encoding"),
    [
        (
            b"Waiting for '\xe2\x9d\xaf|[Pp]db' in session "
            b"routing-enabled-structure_0_64\n(Pdb++)\n",
            "utf-8",
        ),
        (b"hi there", "ascii"),
    ],
)
def testAutoDecode(value, encoding):
    assert value.decode(encoding) == autoDecode(value)


@dataclass(frozen=True)
class HTDCase:
    delta: timedelta
    expected: str


@pytest.mark.parametrize(
    "tc",
    [
        HTDCase(timedelta(), "0:00:00"),
        HTDCase(timedelta(seconds=1), "0:00:01"),
        HTDCase(timedelta(seconds=59), "0:00:59"),
        HTDCase(timedelta(minutes=1), "0:01:00"),
        HTDCase(timedelta(minutes=59), "0:59:00"),
        HTDCase(timedelta(hours=1), "1:00:00"),
        HTDCase(timedelta(hours=23), "23:00:00"),
        HTDCase(timedelta(days=6), "6 days, 0:00:00"),
        HTDCase(timedelta(days=4, hours=3, minutes=2, seconds=1), "4 days, 3:02:01"),
        HTDCase(timedelta(milliseconds=900), "0:00:01"),
    ],
)
def testHumanTimeDeltaSecs(tc: HTDCase) -> None:
    b = datetime.now()
    a = b + tc.delta
    actual = humanTimeDeltaSecs(a, b)
    assert tc.expected == actual

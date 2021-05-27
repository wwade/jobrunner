#!/usr/bin/env python
# Copyright (c) 2021 Arista Networks, Inc.  All rights reserved.
# Arista Networks, Inc. Confidential and Proprietary.

from __future__ import absolute_import, division, print_function

import pytest

from jobrunner.utils import autoDecode


@pytest.mark.parametrize(("value", "encoding"), [
    (b"Waiting for '\xe2\x9d\xaf|[Pp]db' in session "
     b"routing-enabled-structure_0_64\n(Pdb++)\n", "utf-8"),
    (b"hi there", "ascii"),
])
def testAutoDecode(value, encoding):
    assert value.decode(encoding) == autoDecode(value)

#!/usr/bin/env python
from __future__ import absolute_import, division, print_function

import sys

import simplejson as json

print(json.dumps(sys.argv[1:]))

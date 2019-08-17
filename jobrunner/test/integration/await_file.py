#!/usr/bin/env python
from __future__ import absolute_import, division, print_function
import sys
import time
import os.path

fileName = sys.argv[1]
exitCode = int(sys.argv[2])
for _ in range(1000):
    time.sleep(0.1)
    if os.path.exists(fileName):
        sys.exit(exitCode)

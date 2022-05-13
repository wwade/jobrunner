#!/usr/bin/env python
import json
import os
import sys

print(json.dumps(sys.argv[1:]))
dumpFile = os.getenv("SEND_EMAIL_DUMP_FILE")
if dumpFile:
    with open(dumpFile, "w", encoding="utf-8") as fp:
        json.dump(sys.argv[1:], fp)

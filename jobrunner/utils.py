from __future__ import absolute_import, division, print_function

import collections
import datetime
import errno
import inspect
import os
import signal
import sys
import time

import dateutil.tz

PRUNE_NUM = 5000
DATETIME_FMT = "%a %b %e, %Y %X %Z"
STOP_STOP = -1000
STOP_ABORT = -1001
STOP_DONE = -1002
STOP_DEPFAIL = -1003
SPECIAL_STATUS = [STOP_STOP, STOP_ABORT, STOP_DONE, STOP_DEPFAIL]

SPACER_EACH = "========================================"
SPACER = SPACER_EACH + SPACER_EACH


class ModState(object):
    def __init__(self):
        self._plugins = None

    @property
    def plugins(self):
        return self._plugins

    @plugins.setter
    def plugins(self, plugins):
        self._plugins = plugins


MOD_STATE = ModState()


def locked(func):
    def _locked(self, *args, **kwargs):
        self.lock()
        ret = func(self, *args, **kwargs)
        self.unlock()
        return ret
    return _locked


def utcNow():
    return datetime.datetime.utcnow().replace(tzinfo=dateutil.tz.tzutc())


def dateTimeToJson(dtObj):
    if dtObj is None:
        return None
    return [
        dtObj.year,
        dtObj.month,
        dtObj.day,
        dtObj.hour,
        dtObj.minute,
        dtObj.second,
        dtObj.microsecond,
    ]


def dateTimeFromJson(dtJson):
    if dtJson is None:
        return None
    args = list(dtJson)
    args.append(dateutil.tz.tzutc())
    return datetime.datetime(*args)


def pidDebug(*args):
    print("+%05d+ %s" % (os.getpid(), " ".join(map(str, args))))


FnDetails = collections.namedtuple('FnDetails', 'filename, lineno, funcname')


def stackDetails(depth=0):
    caller = inspect.stack()[depth + 1]
    return FnDetails(caller[1], caller[2], caller[3])


def workspaceIdentity():
    return MOD_STATE.plugins.workspaceIdentity()


def getAllowed():
    allowed = (range(ord('a'), ord('z') + 1) +
               range(ord('A'), ord('Z') + 1) +
               range(ord('0'), ord('9') + 1) +
               [ord(char) for char in ['_', '#']])
    ret = [chr(char) for char in allowed]
    return ret


def keyEscape(inp):
    allowed = getAllowed()
    ret = ""
    for char in inp:
        if char in allowed:
            ret += char
        else:
            ret += '+'
    return ret


class Debugger(object):
    msgQueue = []
    quiet = False


_DEBUGGER = Debugger()


def setQuiet(value):
    _DEBUGGER.quiet = value


def quiet():
    return _DEBUGGER.quiet == "quiet"


def robot():
    return _DEBUGGER.quiet == "robot"


def doMsg(*args):
    msg = " ".join(map(str, args))
    if quiet():
        _DEBUGGER.msgQueue.append(msg)
    elif robot():
        return
    else:
        print(msg)


def robotInfo(*info):
    if not robot():
        return
    msg = []
    for item in info:
        if isinstance(item, dict):
            for key, val in item.items():
                msg.append('{}={}'.format(key, val))
        else:
            msg.append(str(item))
    if robot():
        print('\x00'.join(msg))
        sys.stdout.flush()


def showMsgs():
    print('\n'.join(_DEBUGGER.msgQueue) + '\n')
    _DEBUGGER.msgQueue = []


def killProcGroup(pid):
    pgrp = os.getpgid(pid)
    sig = signal.SIGINT
    os.killpg(pgrp, sig)
    for sig in [signal.SIGINT, signal.SIGTERM,
                signal.SIGKILL, signal.SIGKILL]:
        try:
            os.killpg(pgrp, sig)
            print('killpg', pgrp, 'signal', sig)
        except OSError as err:
            if err.errno == errno.ESRCH:
                # no such process
                return
        print('Still trying to kill pgrp', pgrp)
        time.sleep(1.5)

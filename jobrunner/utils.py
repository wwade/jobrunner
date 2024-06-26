import collections
from contextlib import contextmanager
import datetime
import errno
import fcntl
import logging
import os
import signal
import subprocess
import sys
import tempfile
import time
from typing import Optional

import chardet
import dateutil.tz
from six import text_type
from six.moves import map, range

from .compat import encoding_open
from .plugins import Plugins

PRUNE_NUM = 5000
DATETIME_FMT = "%a %b %e, %Y %X %Z"
STOP_STOP = -1000
STOP_ABORT = -1001
STOP_DONE = -1002
STOP_DEPFAIL = -1003
SPECIAL_STATUS = [STOP_STOP, STOP_ABORT, STOP_DONE, STOP_DEPFAIL]

SPACER_EACH = "========================================"
SPACER = SPACER_EACH + SPACER_EACH

LOG = logging.getLogger(__name__)


def strForEach(value):
    try:
        return text_type(value)
    except (UnicodeDecodeError, UnicodeEncodeError):
        LOG.debug("%r", value, exc_info=True)
        return f"{value!r}"


def sprint(*args, **kwargs):
    """sprint: "safe" print - ignore IOError"""
    try:
        print(*list(map(strForEach, args)), **kwargs)
    except IOError:
        LOG.debug("sprint ignore IOError", exc_info=True)
    except (UnicodeEncodeError, UnicodeDecodeError):
        print("codec error", repr(args))
        LOG.debug("%r", args, exc_info=True)
    except BaseException:
        LOG.debug("sprint caught error", exc_info=True)
        raise


class ModState(object):
    def __init__(self) -> None:
        self._plugins: Optional[Plugins] = None

    @property
    def plugins(self) -> Optional[Plugins]:
        return self._plugins

    @plugins.setter
    def plugins(self, plugins: Plugins) -> None:
        self._plugins = plugins


MOD_STATE = ModState()


def locked(func):
    def _locked(self, *args, **kwargs):
        isLocked = self.isLocked()
        if not isLocked:
            self.lock()
        ret = func(self, *args, **kwargs)
        if not isLocked:
            self.unlock()
        return ret
    return _locked


@contextmanager
def lockedSection(jobs):
    jobs.lock()
    try:
        yield
    except BaseException:
        LOG.debug("lockedSection exception", exc_info=True)
        raise
    finally:
        jobs.unlock()


@contextmanager
def maybeUnlock(jobs):
    isLocked = jobs.isLocked()
    if isLocked:
        jobs.unlock()
    try:
        yield
    finally:
        if isLocked:
            jobs.lock()


def unlocked(func):
    def _unlocked(self, *args, **kwargs):
        with maybeUnlock(self):
            return func(self, *args, **kwargs)
    return _unlocked


def utcNow():
    return datetime.datetime.utcnow().replace(tzinfo=dateutil.tz.tzutc())


class FileLock(object):
    def __init__(self, filename):
        self._filename = filename
        self._fp = None

    def __del__(self):
        if self._fp:
            sprint(os.getpid(),
                   "WARNING: termination without unlocking",
                   file=sys.stderr)
            self.unlock()

    def isLocked(self):
        return bool(self._fp)

    def lock(self):
        assert self._fp is None
        self._fp = encoding_open(self._filename, "a")
        fcntl.flock(self._fp, fcntl.LOCK_EX)

    def unlock(self):
        assert self._fp is not None
        self._fp.close()
        self._fp = None


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
    sprint("+%05d+ %s" % (os.getpid(), " ".join(map(str, args))))


FnDetails = collections.namedtuple("FnDetails", "filename, lineno, funcname")


def workspaceIdentity() -> Optional[str]:
    assert MOD_STATE.plugins
    return MOD_STATE.plugins.workspaceIdentity()


def workspaceProject() -> Optional[str]:
    assert MOD_STATE.plugins
    proj, ok = MOD_STATE.plugins.workspaceProject()
    if ok:
        return proj
    return os.getenv("WP")


def _getAllowed():
    allowed = (list(range(ord("a"), ord("z") + 1)) +
               list(range(ord("A"), ord("Z") + 1)) +
               list(range(ord("0"), ord("9") + 1)) +
               [ord(char) for char in ["_", "#"]])
    ret = [chr(char) for char in allowed]
    return ret


def keyEscape(inp):
    allowed = _getAllowed()
    ret = ""
    for char in inp:
        if char in allowed:
            ret += char
        else:
            ret += "+"
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


def cmp_(first, second):  # pylint: disable=invalid-name
    return (first > second) - (first < second)


def doMsg(*args):
    msg = " ".join(map(str, args))
    LOG.debug("doMsg(%s)", repr(args))
    if quiet():
        LOG.debug("enqueue message")
        _DEBUGGER.msgQueue.append(msg)
    elif robot():
        LOG.debug("robot - skip message")
        return
    else:
        LOG.debug("print message")
        sprint(msg)


def robotInfo(*info):
    if not robot():
        return
    msg = []
    for item in info:
        if isinstance(item, dict):
            for key, val in item.items():
                msg.append("{}={}".format(key, val))
        else:
            msg.append(str(item))
    if robot():
        sprint("\x00".join(msg))
        sys.stdout.flush()


def showMsgs():
    LOG.debug("showMsgs for %d messages", len(_DEBUGGER.msgQueue))
    sprint("\n".join(_DEBUGGER.msgQueue) + "\n")
    _DEBUGGER.msgQueue = []
    LOG.debug("showMsgs finished")


def killWithSignal(pgrp, signum):
    try:
        os.killpg(pgrp, signum)
        os.killpg(pgrp, 0)
    except OSError as err:
        sprint("killpg", pgrp, signum, "->", err)
        if err.errno == errno.ESRCH:
            # no such process -> it's done!
            return True
        elif err.errno == errno.EPERM:
            # Operation not permitted
            return False
        else:
            sprint("killpg", pgrp, signum, "->", err)

    return False


def safeSleep(howLong, jobs):
    with maybeUnlock(jobs):
        time.sleep(howLong)


def killProcGroup(pgrp, jobs):
    if not pgrp:
        sprint("Unable to kill (no process group)")
        return False
    sigQueue = 5 * [signal.SIGINT] + [signal.SIGTERM, signal.SIGKILL]
    for signum in sigQueue:
        try:
            os.killpg(pgrp, signum)
            try:
                os.killpg(pgrp, 0)
            except OSError as checkForEsrch:
                if checkForEsrch.errno == errno.ESRCH:
                    # no such process -> it's done!
                    sprint("Killed", pgrp, "with signal", signum)
                    return True
                raise
        except OSError as err:
            if err.errno == errno.ESRCH:
                # no such process -> it's done!
                sprint("Killed", pgrp, "with signal", signum)
                return True
            elif err.errno == errno.EPERM:
                # Operation not permitted
                sprint("Unable to kill", pgrp, "(operation not permitted)")
                return False
            else:
                sprint("killpg", pgrp, signum, "->", err)
        sprint("Still trying to kill pgrp", pgrp)
        if jobs is None:
            time.sleep(1.5)
        else:
            safeSleep(1.5, jobs)
    sprint("Unable to kill", pgrp)
    return False


def sudoKillProcGroup(pgrp):
    if not pgrp:
        return "No PID for job?"
    script = r"""
from __future__ import absolute_import, division, print_function
import os
import sys
sys.path = sys.argv[1].split(":-:")
import jobrunner.utils
assert os.getuid() == 0
pgrp = int(sys.argv[2])
jobrunner.utils.killProcGroup(pgrp, None)
"""
    myPath = ":-:".join(sys.path)
    LOG.debug("argv: %r, exec: %s", sys.argv, sys.executable)
    with tempfile.NamedTemporaryFile(mode="w") as tmpf:
        tmpf.write(script)
        tmpf.flush()
        cmd = ["sudo", sys.executable, tmpf.name, myPath, str(pgrp)]
        try:
            subprocess.check_call(cmd)
        except subprocess.CalledProcessError as error:
            LOG.debug("cmd %r => error=%s", cmd, error, exc_info=True)
            return error.output
    return None


def autoDecode(byteArray: bytes) -> str:
    detected = chardet.detect(byteArray)
    if not detected:
        return byteArray.decode()

    encoding = detected["encoding"]
    if detected["confidence"] < 0.8:  # very arbitrary
        LOG.debug("char encoding below confidence level 0.8 (%r). "
                  "Fall back to UTF-8.", detected)
        encoding = "utf-8"

    return byteArray.decode(encoding)


def humanTimeDeltaSecs(a: datetime.datetime, b: datetime.datetime) -> str:
    """
    Returns a human readable string for the time difference a - b.
    """
    seconds = round((a - b).total_seconds(), 0)
    return f"{datetime.timedelta(seconds=seconds)}"

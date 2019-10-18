from __future__ import absolute_import, division, print_function

from curses.ascii import isprint
import os
import pipes

import dateutil.tz

import jobrunner.utils as utils

from .utils import (
    dateTimeFromJson,
    dateTimeToJson,
    doMsg,
    keyEscape,
    locked,
    robotInfo,
    utcNow,
    workspaceIdentity,
)


def getUtcTime(val):
    if val and not val.tzinfo:
        val = val.replace(tzinfo=dateutil.tz.tzutc())
    return val


def cmdString(cmd):
    return " ".join(map(pipes.quote, cmd))


class JobInfo(object):
    # pylint: disable=too-many-instance-attributes,too-many-public-methods
    def __init__(self, uidx, key=None):
        self.prog = None
        self.args = None
        self.cmd = None
        self.reminder = None
        self.pwd = None
        self._autoJob = None
        self._create = utcNow()
        self._start = None
        self._stop = None
        self._depends = None
        self._alldeps = set()
        self._host = os.getenv('HOSTNAME')
        self._user = os.getenv('USER')
        self._env = {key: value for key, value in os.environ.items()}
        self._workspace = workspaceIdentity()
        self._proj = os.getenv('WP')
        self._rc = None
        self.logfile = None
        self._key = key
        self._persistKey = None
        self._persistKeyGenerated = None
        self._hasTime = False
        self._blocked = False
        self.pid = None
        self._parent = None
        self._uidx = uidx
        self._mailJob = False
        self._isolate = False

    def __getstate__(self):
        odict = self.__dict__.copy()
        del odict['_parent']
        return odict

    def __setstate__(self, dct):
        self.__dict__.update(dct)

    def lock(self):
        self._parent.lock()

    def unlock(self):
        self._parent.unlock()

    @property
    def autoJob(self):
        try:
            return self._autoJob
        except AttributeError:
            return False

    @autoJob.setter
    def autoJob(self, value):
        self._autoJob = value

    @property
    def isolate(self):
        try:
            return self._isolate
        except AttributeError:
            return False

    @isolate.setter
    def isolate(self, value):
        self._isolate = value

    @property
    def mailJob(self):
        try:
            return self._mailJob
        except AttributeError:
            return False

    @mailJob.setter
    def mailJob(self, value):
        assert isinstance(value, bool)
        self._mailJob = value

    @property
    def parent(self):
        return self._parent

    @parent.setter
    def parent(self, parent):
        self._parent = parent

    @property
    def proj(self):
        return self._proj

    @property
    def rc(self):
        return self._rc

    @property
    def startTime(self):
        return getUtcTime(self._start)

    @property
    def createTime(self):
        return getUtcTime(self._create)

    @property
    def stopTime(self):
        return getUtcTime(self._stop)

    def persistKeyGeneratedGet(self):
        return self._persistKeyGenerated
    persistKeyGenerated = property(persistKeyGeneratedGet)

    def wsBasename(self):
        return getattr(self, '_workspace')

    def cmpCommon(self, other, order):
        for func in order:
            rc = func(other)
            if rc != 0:
                return rc

        rc = cmp(self.persistKeyGenerated, other.persistKeyGenerated)
        if rc != 0:
            return rc
        return cmp(self.cmd, other.cmd)

    def cmpCreate(self, other):
        try:
            rc = cmp(self.createTime, other.createTime)
        except AttributeError:
            rc = 0
        return rc

    def cmpStart(self, other):
        myStart = self.startTime
        otherStart = other.startTime
        if myStart is None:
            myStart = utcNow()
        if otherStart is None:
            otherStart = utcNow()
        return cmp(myStart, otherStart)

    def cmpStop(self, other):
        return cmp(self.stopTime, other.stopTime)

    def cmpActive(self, other):
        return self.cmpCommon(
            other, [self.cmpCreate, self.cmpStart, self.cmpStop])

    def cmpInactive(self, other):
        return self.cmpCommon(
            other, [self.cmpStop, self.cmpStart, self.cmpCreate])

    def __cmp__(self, other):
        if not isinstance(other, type(self)):
            return -1
        if self._stop is None:
            return self.cmpActive(other)
        else:
            return self.cmpInactive(other)

    def __hash__(self):
        hashVal = 0
        hashVal += hash(self._persistKeyGenerated)
        for char in self.cmd:
            hashVal += hash(char)
        hashVal += hash(len(self.cmd))
        hashVal += hash(self.pwd)
        hashVal += hash(self._user)
        hashVal += hash(self._start)
        return hashVal

    @property
    def cmdStr(self):
        try:
            if self.reminder is not None:
                return self.reminder
        except AttributeError:
            pass
        return cmdString(self.cmd)

    @property
    def key(self):
        if self._key:
            return self._key
        self._hasTime = True
        keySource = self.prog if self.prog else self.reminder
        self._key = (utcNow().strftime("%s") +
                     str(self._uidx) + "_" +
                     keyEscape(keySource))
        doMsg("set key", self._key)
        robotInfo("new", {"key": self._key})
        return self._key

    @property
    def permKey(self):
        return self._persistKeyGenerated

    def genPersistKey(self, inactive):
        if self._persistKeyGenerated is not None:
            return
        assert self._key
        persistKey = self._key
        if persistKey not in inactive.db:
            inactive[persistKey] = 'Not a valid entry'
        self._persistKeyGenerated = persistKey
        return

    def persistKey(self, _inactive):
        if self._persistKey:
            return self._persistKey
        elif self._key:
            return self._key
        else:
            assert False, "invalid call to persistKey()"
            return None

    def setCmd(self, cmd, reminder=None):
        self.pwd = os.getcwd()
        if cmd is not None:
            self.cmd = cmd
            self.prog = cmd[0]
            self.args = cmd[1:]
        else:
            assert reminder is not None, "Must specify reminder"
            self.reminder = reminder
            self.cmd = ["(reminder)"]
            self.prog = None
            self.args = None

    @staticmethod
    def setDepArray(onWhat):
        if onWhat:
            ret = []
            for job in onWhat:
                ret.append(job.key)
        else:
            ret = None

    @property
    def depends(self):
        return self._depends

    @depends.setter
    def depends(self, onWhat):
        if onWhat:
            self._depends = []
            for job in onWhat:
                self._alldeps.add(job.key)
                self._depends.append(job.key)
        else:
            self._depends = None

    @property
    def alldeps(self):
        try:
            return self._alldeps
        except AttributeError:
            return set()

    @locked
    def setDependencies(self, parent, onWhat):
        self.depends = onWhat
        self.genPersistKey(parent.inactive)
        parent.active[self.key] = self

    @locked
    def blocked(self, parent):
        self._blocked = True
        self.genPersistKey(parent.inactive)
        parent.active[self.key] = self

    @locked
    def unblocked(self, parent):
        self._blocked = False
        self.genPersistKey(parent.inactive)
        parent.active[self.key] = self

    @locked
    def start(self, parent):
        self._start = utcNow()
        parent.inactive.lastKey = self.key
        self.genPersistKey(parent.inactive)
        parent.active[self.key] = self

    @locked
    def stop(self, parent, rc):
        self._stop = utcNow()
        self._rc = rc
        self.pid = None
        del parent.active[self.key]
        self.genPersistKey(parent.inactive)
        k = self.persistKey(parent.inactive)
        parent.inactive[k] = self

    def killPgrp(self):
        if not self.pid:
            print("Not running")
        try:
            utils.killProcGroup(self.pid)
        except OSError as error:
            print("Unable to kill process group for", self.pid, error)

    @locked
    def pidIs(self, parent, pid):
        self.pid = pid
        parent.active[self.key] = self

    def getDuration(self):
        if self.startTime is None:
            return "Blocked"
        stop = self.stopTime or utcNow()
        return str(stop - self.startTime).split('.')[0]

    def removeLog(self, verbose):
        if os.access(self.logfile, os.F_OK):
            if verbose:
                print("Remove logfile '%s'" % self.logfile)
            os.unlink(self.logfile)

    @staticmethod
    def escEnv(value):
        ret = ""
        for char in value:
            if isprint(char):
                ret += char
            else:
                ret += "\\x%02x" % ord(char)
        return ret

    def getEnvironment(self):
        ret = "\n"
        for k, v in sorted(self._env.iteritems()):
            ret += "\t%s=%s\n" % (self.escEnv(k), self.escEnv(v))
        return ret

    def env(self, key):
        if key in self._env:
            return self.escEnv(self._env[key])
        return None

    @property
    def environ(self):
        return self._env

    def matchEnv(self, env, value):
        return value is None or value == self.environ.get(env, None)

    def getState(self):
        if self._blocked:
            return "Blocked"
        elif self._stop:
            xStatus = {
                utils.STOP_STOP: 'Stopped with --stop',
                utils.STOP_DONE: 'Completed Reminder',
                utils.STOP_ABORT: 'Interrupted',
                utils.STOP_DEPFAIL: 'Dependent Job Failed',
            }
            rcStatus = (" (" + xStatus[self.rc] +
                        ")" if self.rc in xStatus else '')
            return "Finished" + rcStatus
        else:
            return "Running"

    def showPersistKey(self):
        if self.permKey != self._key:
            return self.permKey
        else:
            return None

    @property
    def workspace(self):
        return getattr(self, '_workspace')

    def getValue(self, what):
        items = {
            'Program': lambda: self.prog,
            'Directory': lambda: self.pwd,
            'Project': lambda: self._proj,
            'Log': lambda: self.logfile,
            'Args': lambda: cmdString(self.args) if self.args else None,
            'Command': lambda: cmdString(self.cmd),
            'Start': lambda: self.timeStr(self.startTime),
            'Stop': lambda: self.timeStr(self._stop),
            'Duration': self.getDuration,
            'Exit Status': lambda: self._rc,
            'User': lambda: self._user,
            'Host': lambda: self._host,
            'Environment': self.getEnvironment,
            'Workspace': lambda: self.workspace,
            'Key': lambda: self._key,
            'Reminder': lambda: self.reminder,
            'Persistent Key': self.showPersistKey,
            'State': self.getState,
            'PID': lambda: self.pid,
            'Isolated': lambda: self.isolate,
        }
        try:
            return items[what]()
        except AttributeError:
            return "N/A"

    def showInOrder(self, order, level):
        longLine = 0
        for k in order:
            if len(k) > longLine:
                longLine = len(k)
        ret = utils.SPACER + "\n"
        for k in order:
            fmt = "%%-%ds   %%s\n" % longLine
            try:
                v = self.getValue(k)
                if level:
                    if v is None:
                        v = "N/A"
                if v is not None:
                    ret += fmt % (k, v)
            except AttributeError:
                pass
        ret += utils.SPACER
        return ret

    def showReminder(self):
        order = [
            'Key',
            'Persistent Key',
            'Reminder',
        ]
        if self._stop:
            order += ['State']
        order += [
            'Directory',
            'Workspace',
            'Start',
            'Stop',
        ]
        return self.showInOrder(order, None)

    def detail(self, level):
        if self.reminder:
            return self.showReminder()

        order = [
            'Key',
            'Persistent Key',
            'Program',
            'Args',
            'State',
            'Exit Status',
            'Directory',
            'Workspace',
            'Project',
            'Log',
            'Start',
            'Stop',
            'Duration',
            'Isolated',
            'Command',
            'PID',
        ]
        verb1 = [
            'User',
            'Host',
        ]
        verb2 = [
            'Environment'
        ]

        if level:
            if len(level) >= 1:
                order += verb1
            if len(level) >= 2:
                order += verb2
        return self.showInOrder(order, level)

    @staticmethod
    def localTime(val):
        utc = val.replace(tzinfo=dateutil.tz.tzutc())
        return utc.astimezone(dateutil.tz.tzlocal())

    def timeStr(self, val):
        local = self.localTime(val)
        return local.strftime(utils.DATETIME_FMT)

    def __str__(self):
        rc = ""
        if self.stopTime and self._rc is not None:
            rc = "rc=%-3d " % self._rc
        cmdStr = self.cmdStr
        try:
            if self.reminder is not None:
                cmdStr = "Reminder: " + self.reminder
        except AttributeError:
            pass
        return "%s %s[%s] %s" % (self.getDuration(), rc, self.key, cmdStr)


DATETIME_KEYS = ('_create', '_start', '_stop')


def encodeJobInfo(obj):
    if isinstance(obj, JobInfo):
        odict = obj.__getstate__()
        for dateTimeKey in DATETIME_KEYS:
            odict[dateTimeKey] = dateTimeToJson(odict.get(dateTimeKey))
        odict['_alldeps'] = list(odict.get('_alldeps', []))
        return odict
    raise TypeError(repr(obj) + " is not JSON serializable")


def decodeJobInfo(odict):
    if '_uidx' not in odict:
        return odict
    uidx = odict['_uidx']
    newJob = JobInfo(uidx)
    for dateTimeKey in DATETIME_KEYS:
        odict[dateTimeKey] = dateTimeFromJson(odict.get(dateTimeKey))
    odict['_alldeps'] = set(odict.get('_alldeps', set()))
    newJob.__setstate__(odict)
    return newJob

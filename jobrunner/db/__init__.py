from __future__ import absolute_import, division, print_function

from datetime import datetime
from functools import cmp_to_key
import logging
import os
import os.path
import sys
import tempfile
import time
from uuid import uuid4

from dateutil import parser
from dateutil.tz import tzlocal, tzutc
import simplejson as json
import six
from six import text_type
from six.moves import filter

import jobrunner.utils as utils

from ..info import JobInfo, decodeJobInfo, encodeJobInfo
from ..service import service
from ..utils import (
    FileLock,
    cmp_,
    dateTimeFromJson,
    dateTimeToJson,
    doMsg,
    pidDebug,
    safeSleep,
    sprint,
    stackDetails,
    utcNow,
)

NUM_RECENT = 100
PRUNE_NUM = 5000

LOG = logging.getLogger(__name__)
LOGLOCK = logging.getLogger(__name__ + ".lock")


class DatabaseMeta(object):
    # pylint: disable=too-many-instance-attributes
    SV = '_schemaVersion_'
    LASTKEY = '_lastKey_'
    ITEMCOUNT = '_itemCount_'
    RECENT = '_recentItems_'
    IDX = '_currentIndex_'
    LASTJOB = '_lastJob_'
    CHECKPOINT = '_checkPoint_'
    initvals = frozenset([SV, LASTKEY, LASTJOB, ITEMCOUNT, CHECKPOINT])
    special = frozenset(list(initvals) + [RECENT, IDX])

    def defaultValueGenerator(self, schemaVersion):
        yield self.SV, schemaVersion
        yield self.LASTKEY, ""
        yield self.LASTJOB, ""
        yield self.ITEMCOUNT, "0"
        yield self.CHECKPOINT, ""


def resolveDbFile(config, filename):
    return os.path.join(config.dbDir, filename)


class DatabaseBase(DatabaseMeta):
    def __init__(self, parent, config, instanceId):
        self.config = config
        self._parent = parent
        self._instanceId = instanceId
        self.ident = 'N/A'

    @property
    def db(self):
        raise NotImplementedError

    def filterJobs(self, k):
        return k not in self.special

    def iteritems(self):
        return six.iteritems(self.db)

    def getCount(self):
        return int(self.db[self.ITEMCOUNT])

    def setCount(self, inc):
        curCount = self.count
        curCount += inc
        if curCount < 0:
            curCount = 0
        self.db[self.ITEMCOUNT] = str(curCount)
    count = property(getCount, setCount)

    def getCheckpoint(self):
        try:
            return dateTimeFromJson(json.loads(self.db[self.CHECKPOINT]))
        except (KeyError, EOFError, json.scanner.JSONDecodeError):
            epoch = datetime.utcfromtimestamp(0)
            return epoch.replace(tzinfo=tzutc())

    def setCheckpoint(self, val):
        if isinstance(val, str):
            if val.strip() == ".":
                checkpoint = utcNow()
            else:
                checkpoint = parser.parse(val)
                if not checkpoint.tzinfo:
                    checkpoint = checkpoint.replace(tzinfo=tzlocal())
        elif isinstance(val, datetime):
            if not val.tzinfo:
                checkpoint = val.replace(tzinfo=tzlocal())
            else:
                checkpoint = val
        else:
            raise ValueError(
                "Expecting either a string or a datetime.datetime")
        utc = checkpoint.astimezone(tzutc())
        self.db[self.CHECKPOINT] = json.dumps(dateTimeToJson(utc))

    checkpoint = property(getCheckpoint, setCheckpoint)

    def lastKeyGet(self):
        return self.db[self.LASTKEY]

    def lastKeySet(self, key):
        self.db[self.LASTKEY] = key
    lastKey = property(lastKeyGet, lastKeySet)

    def lastJobGet(self):
        return self.db[self.LASTJOB]

    def lastJobSet(self, key):
        self.db[self.LASTJOB] = key
    lastJob = property(lastJobGet, lastJobSet)

    def keys(self):
        return list(filter(self.filterJobs, list(self.db.keys())))

    def recentGet(self):
        if self.RECENT in self.db:
            try:
                return json.loads(self.db[self.RECENT])
            except json.JSONDecodeError:
                return None
        else:
            return None

    def recentSet(self, key):
        recent = self.recent
        if recent is None:
            recent = []
        recent.insert(0, key)
        if len(recent) > NUM_RECENT:
            recent = recent[:NUM_RECENT]
        self.db[self.RECENT] = json.dumps(recent)
    recent = property(recentGet, recentSet)

    def recentDel(self, key):
        recent = self.recent
        if recent and key in recent:
            recent.remove(key)
            self.db[self.RECENT] = json.dumps(recent)

    def __setitem__(self, key, value):
        if "lock" in self.config.debugLevel:
            pidDebug(self.ident, "[%s]" % key, "=", repr(value))
        if key not in self.db:
            self.count = 1
            self.recent = key
        if key == self.SV:
            self.db[key] = repr(value)
        else:
            self.db[key] = json.dumps(value, default=encodeJobInfo)

    def __delitem__(self, key):
        if key in self.db:
            self.count = -1
        del self.db[key]
        self.recentDel(key)

    def __getitem__(self, key):
        if key == self.SV:
            return self.db[key]
        else:
            ret = json.loads(self.db[key], object_hook=decodeJobInfo)
            if isinstance(ret, JobInfo):
                ret.parent = self._parent
            return ret

    def __contains__(self, key):
        return key in self.db

    def __str__(self):
        return "%s DB %d '%s' ver %s" % (
            self.__class__.__name__, self.count, self.ident, self.db[self.SV])

    def uidx(self):
        if self.IDX in self.db:
            cur = json.loads(self.db[self.IDX])
        else:
            cur = 0
        self.db[self.IDX] = json.dumps(cur + 1)
        return cur


def reminderWatchSummary(activeReminder):
    if activeReminder:
        return " (\033[32m{} reminders\033[0m)".format(len(activeReminder))
    else:
        return ""


def reminderWatchFull(activeReminder):
    reminders = ""
    if activeReminder:
        reminderList = []
        for remindJob in activeReminder:
            workspace = ""
            wsVal = remindJob.wsBasename()
            if wsVal:
                workspace = "%s: " % wsVal
            reminderList.append(
                '[%s%s]' %
                (workspace, remindJob.cmdStr))
        reminders = " " + " ".join(reminderList)
    return reminders


class JobsBase(object):
    # pylint: disable=too-many-public-methods
    # pylint: disable=too-many-instance-attributes
    def __init__(self, config, plugins):
        self.config = config
        self.plugins = plugins
        self._instanceId = uuid4().hex
        self.displayPending = set()
        self.active = None
        self.inactive = None
        self._lock = FileLock(self.config.lockFile)

    def setDbCaching(self, enabled):
        pass

    def debugPrint(self, msg):
        if "lock" not in self.config.debugLevel:
            return
        fnDetails = stackDetails(depth=2)
        if fnDetails.funcname == 'lock' or fnDetails.funcname == 'unlock':
            fnDetails = stackDetails(depth=3)
        if fnDetails.funcname == '_locked':
            fnDetails = stackDetails(depth=4)
        pidDebug(msg, "from",
                 fnDetails.filename, fnDetails.funcname, fnDetails.lineno)

    def isLocked(self):
        raise NotImplementedError

    def lock(self):
        LOGLOCK.debug("lock DB")
        self.debugPrint("< LOCK DB")

    def unlock(self):
        LOGLOCK.debug("unlock DB")
        self.debugPrint("< UNLOCK DB")

    def prune(self, exceptNum=None):
        allJobs = []
        db = self.inactive
        for jobKey in db.keys():
            job = db[jobKey]
            assert job.key == jobKey, 'job key mismatch "{}" for job {}'.format(
                jobKey, job)
            allJobs.append(job)
        allJobs.sort()
        limit = PRUNE_NUM if exceptNum is None else exceptNum
        if len(allJobs) > limit:
            for job in allJobs[: -1 * limit]:
                if self.config.verbose:
                    sprint("Prune '%s'" % job.key)
                job.removeLog(self.config.verbose)
                del self.inactive[job.key]

    @staticmethod
    def getDbSorted(db, _limit, useCp=False, filterWs=False):
        if useCp:
            cpUtc = db.checkpoint
        if filterWs:
            curWs = utils.workspaceIdentity()
        jobList = []
        for k in db.keys():
            if db.filterJobs(k):
                try:
                    job = db[k]
                except KeyError:
                    continue
                if useCp:
                    refTime = job.createTime
                    if not refTime or refTime < cpUtc:
                        continue
                if filterWs:
                    if job.workspace != curWs:
                        continue
                jobList.append(job)
#             if _limit and len( jobList ) > _limit:
#                break
        jobList.sort(reverse=False)
        return jobList

    def walkDepTree(self, func, db, depends, depth, **kwargs):
        for dep in depends:
            if dep in db:
                j = db[dep]
                if not func(j, depth, **kwargs):
                    return False
                if j.depends:
                    self.walkDepTree(func, db, j.depends, depth + 1, **kwargs)
        return True

    @staticmethod
    def printDepJob(job, depth):
        fmt = "%%-%ds->" % (depth * 2)
        sprint(fmt % "", job)
        return True

    def printDepTree(self, db, depends):
        self.walkDepTree(self.printDepJob, db, depends, 1)

    def filterJobs(self, db, limit, filterWs=False,
                   filterPane=False, useCp=False):
        # pylint: disable=too-many-arguments
        jobList = self.getDbSorted(db, limit, useCp)
        if filterWs:
            curWs = utils.workspaceIdentity()
            if curWs:
                jobList = [j for j in jobList if curWs == j.workspace]
        if filterPane:
            curPane = os.getenv('TMUX_PANE', None)
            if curPane:
                jobList = [
                    j for j in jobList if j.matchEnv(
                        'TMUX_PANE', curPane)]
        return jobList

    def listDb(self, db, limit, filterWs=False, filterPane=False, useCp=False,
               includeReminders=False):
        # pylint: disable=too-many-arguments
        jobList = self.filterJobs(db, limit, filterWs, filterPane, useCp)
        hasDeps = False
        for job in jobList:
            if not includeReminders and job.reminder:
                continue
            if job.depends:
                hasDeps = self.walkDepTree(
                    lambda j, d: d == 1, db, job.depends, 1)
        if hasDeps:
            sprint(utils.SPACER)
        for job in jobList:
            if not includeReminders and job.reminder:
                continue
            if self.config.verbose:
                sprint(job.detail(self.config.verbose[1:]))
            else:
                if db is self.active:
                    sprint(job)
                    if job.depends:
                        self.printDepTree(db, job.depends)
                    if hasDeps:
                        sprint(utils.SPACER)
                else:
                    sprint(job)
        if not jobList:
            sprint("(None)")

    @staticmethod
    def dotStrForKey(key, active, inactive, attrs=False):
        if key in active:
            job = active[key]
            attrList = ''
        elif key in inactive:
            job = inactive[key]
            colour = 'dimgray' if job.rc == 0 else 'red'
            attrList = ' [color=%s, fontcolor=%s]' % (colour, colour)
        else:
            return 'n/a'
        jobStr = job.cmdStr + '\\n[' + job.key + ']'
        workspace = job.wsBasename()
        if workspace:
            jobStr += '\\nWS: ' + workspace
        ret = '"%s"' % jobStr.replace('"', '\\"')
        if attrs:
            ret += attrList
        return ret

    def makeDot(self, active, inactive, filterWs=False,
                filterPane=False, useCp=False):
        # pylint: disable=too-many-arguments,too-many-locals
        jobList = self.filterJobs(active, limit=None, filterWs=filterWs,
                                  filterPane=filterPane, useCp=useCp)
        dot = ''
        if not jobList:
            dot += 'digraph active { "(None)"; }'
            return dot
        dot += 'digraph active {\n'
        dot += ' rankdir=BT;\n'
        printedSingles = set()
        needsPrinting = set()
        for job in sorted(jobList):
            depSet = set(job.depends) if job.depends else set()
            depSet |= job.alldeps
            if depSet:
                for dep in depSet:
                    jobStr = self.dotStrForKey(job.key, active, inactive)
                    needsPrinting.add(job.key)
                    depStr = self.dotStrForKey(dep, active, inactive)
                    needsPrinting.add(dep)
                    dot += ' %s -> %s;\n' % (jobStr, depStr)
            else:
                printedSingles.add(job.key)
                jobStr = self.dotStrForKey(
                    job.key, active, inactive, attrs=True)
                dot += ' %s;\n' % jobStr
        for key in needsPrinting - printedSingles:
            jobStr = self.dotStrForKey(key, active, inactive, attrs=True)
            dot += ' %s;\n' % jobStr
        dot += '}'
        return dot

    def countInactive(self):
        return len(self.inactive.db) - (len(self.inactive.special) - 1)

    def listActive(self, thisWs, pane, useCp, includeReminders):
        self.listDb(
            self.active,
            None,
            filterWs=thisWs,
            filterPane=pane,
            useCp=useCp,
            includeReminders=includeReminders)

    def listInactive(self, thisWs, pane, useCp, limit=5):
        self.listDb(
            self.inactive,
            limit,
            filterWs=thisWs,
            filterPane=pane,
            useCp=useCp)

    @staticmethod
    def filterJobsWith(job, startTime=True, skipReminders=False):
        if startTime and job.startTime is None:
            return False
        try:
            if skipReminders and job.reminder is not None:
                return False
        except AttributeError:
            pass
        return True

    def getJobMatch(self, key, thisWs, skipReminders=False):
        # pylint: disable=too-many-return-statements,too-many-branches
        if key == '.':
            lastJob = self.active.lastJob
            if lastJob:
                return self.getJobMatch(lastJob, thisWs)

        if key is None:
            jobList = [
                x for x in self.getDbSorted(self.active, None, filterWs=thisWs)
                if self.filterJobsWith(x, skipReminders=skipReminders)]
            if not jobList:
                jobList = [
                    x for x in self.getDbSorted(self.inactive, None, filterWs=thisWs)
                    if self.filterJobsWith(x, skipReminders=skipReminders)]
            if not jobList:
                jobList = self.getDbSorted(
                    self.inactive, None, filterWs=thisWs)
            return jobList[-1]
        elif key in self.active.db:
            # Exact match, try active first
            return self.active[key]
        elif key in self.inactive.db:
            # Exact match, try inactive
            return self.inactive[key]
        else:
            # Search in active jobs
            candidates = []
            curWs = utils.workspaceIdentity()
            for k in self.active.keys():
                j = self.active[k]
                if j.mailJob:
                    continue
                if skipReminders and j.reminder:
                    continue
                jobWs = j.workspace
                if thisWs and curWs != jobWs:
                    continue
                if j.cmdStr.find(key) >= 0:
                    if curWs and jobWs == curWs:
                        return j
                    else:
                        candidates.append(j)
            if candidates:
                return candidates[0]

            candidates = []
            for k in self.inactive.recent:
                if k not in self.inactive:
                    continue
                j = self.inactive[k]
                if isinstance(j, str):
                    continue
                if j.mailJob:
                    continue
                if skipReminders and j.reminder:
                    continue
                jobWs = j.workspace
                if thisWs and curWs != jobWs:
                    continue
                if j.cmdStr.find(key) >= 0:
                    if curWs and jobWs == curWs:
                        return j
                    else:
                        candidates.append(j)
                elif k.startswith(key):
                    candidates.append(j)
            if candidates:
                return candidates[0]

            raise KeyError("No job for key '%s'" % key)

    def getLog(self, key, thisWs, skipReminders=False):
        return self.getJobMatch(key, thisWs, skipReminders).logfile

    def getLogByIndex(self, index, thisWs):
        recent = self.inactive.recent
        key = recent[index]
        return self.getJobMatch(key, thisWs, skipReminders=True).logfile

    def _wait(self, func, desc, verbose, _timeout=None):
        if func():
            return
        if verbose:
            sprint("\nWaiting for %s" % desc)
        while not func():
            safeSleep(1, self)
            if verbose:
                sys.stdout.write(".")
                sys.stdout.flush()

    def waitFor(self, job, verbose):
        self._wait(
            lambda: job.key not in self.active.db,
            "job '%s'" %
            job,
            verbose)

    def inactiveKey(self, key):
        if key not in self.inactive:
            return False
        j = self.inactive[key]
        return isinstance(j, JobInfo)

    def waitInactive(self, key, verbose):
        self._wait(lambda: self.inactiveKey(key), 'inactive key "%s"' % key,
                   verbose)

    def showJobList(self, joblist, tag, clearLen):
        timestr = datetime.now().strftime(utils.DATETIME_FMT)
        joblist = sorted(joblist)
        for jobKey in joblist:
            workspace = ""
            try:
                jCur = self.getJobMatch(jobKey, False)
                if isinstance(jCur, JobInfo):
                    workspace = jCur.wsBasename()
                else:
                    raise KeyError
            except KeyError:
                self.displayPending.add(jobKey)
                continue
            jobStr = str(jCur)
            if jCur.rc != 0:
                jobStr = "\033[41m" + jobStr + "\033[0m"
            details = " [%4s] %s %s" % (tag, workspace, jobStr)
            clearNum = clearLen - len(details)
            if clearNum < 0:
                clearNum = 0
            sprint("%s" % timestr + details + " " * clearNum)

    def getResources(self):
        loads = ['%.0f' % v for v in os.getloadavg()]
        val = 'load: {}/{}/{}'.format(*loads)
        val += self.plugins.getResources(self)
        return val

    def watchActivity(self):
        # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        def _nonReminder(job):
            return job.reminder is None
        curJobList = self.getDbSorted(self.active, None, False)
        curJobs = [j.key for j in filter(_nonReminder, curJobList)]
        first = True
        clearLen = 30
        resUpd = time.time()
        resUpdInterval = 10
        resource = self.getResources()
        blinkEnd = 0
        blinkState = True
        while True:
            activeJobList = self.getDbSorted(self.active, None, False)
            nonReminder = [j for j in activeJobList if j.reminder is None]
            activeReminder = [j for j in activeJobList if j.reminder and j.startTime]
            newJobs = [j.key for j in nonReminder]
            finishedJobs = set(curJobs) - set(newJobs)
            curJobs = newJobs
            sys.stdout.write("\r")
            now = datetime.now()
            timeNow = time.time()
            if finishedJobs:
                self.showJobList(finishedJobs, "done", clearLen)
                blinkEnd = timeNow + 15
            if self.displayPending:
                pending = self.displayPending
                self.displayPending = set()
                self.showJobList(pending, "done", clearLen)
            if first or now.second % 2 == 0:
                first = False
                timestr = now.strftime(utils.DATETIME_FMT)
                count = len(curJobs)
                if count == 0:
                    jobInfo = "No jobs"
                elif count == 1:
                    jobInfo = "1 job"
                else:
                    jobInfo = "%d jobs" % count

                if timeNow >= resUpd + resUpdInterval:
                    resUpd = timeNow
                    resource = self.getResources()

                reminderFunc = (
                    reminderWatchSummary
                    if self.config.uiWatchReminderSummary else reminderWatchFull)
                reminders = reminderFunc(activeReminder)

                outStr = (timestr + " " + jobInfo + " running" + reminders +
                          ", " + resource)
                if timeNow <= blinkEnd:
                    if blinkState:
                        outStr = '\033[45m' + outStr + '\033[0m'
                    blinkState = not blinkState
                else:
                    blinkState = True
                sys.stdout.write(" " * clearLen + "\r" + outStr + '\r')
                clearLen = len(outStr) + 2
                if clearLen < 30:
                    clearLen = 30
                sys.stdout.flush()
            safeSleep(1, self)

    def activityWindow(self, options):
        # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        if options.activity:
            activityLevel = len(options.activity)
        else:
            activityLevel = 1
        today = []
        tnow = datetime.now()
        unow = utcNow()
        perWs = {}
        remind = {}
        for k in self.active.keys():
            j = self.active[k]
            if not j.reminder:
                continue
            if not j.startTime:
                sprint('not started yet', str(j), j.workspace)
                continue
            remind.setdefault(j.workspace, []).append(j)
        for k in self.inactive.keys():
            j = self.inactive[k]
            if not j.stopTime or j.autoJob:
                continue
            if j.rc in utils.SPECIAL_STATUS:
                continue
            if j.reminder:
                continue
            if activityLevel == 1:
                # filter out jobs older than window
                window = options.activity_window or 3
                timeDiff = unow - j.stopTime
                if timeDiff.total_seconds() / 3600 > window:
                    continue
            else:
                # today only
                localTime = j.localTime(j.stopTime)
                if (tnow.year != localTime.year or
                        tnow.month != localTime.month or
                        tnow.day != localTime.day):
                    continue
            today.append(j)
        today.sort()
        for j in reversed(today):
            wkspace = j.workspace

            def _isPass(rc):
                return rc == 0 or rc in utils.SPECIAL_STATUS
            key = 'pass' if _isPass(j.rc) else 'fail'
            if wkspace in perWs and key in perWs[wkspace]:
                continue
            perWs.setdefault(wkspace, {})[key] = j
            age = int((unow - j.stopTime).total_seconds())
            perWs[wkspace]['age'] = min(
                age, perWs[wkspace].get(
                    'age', float('inf')))

        def _byAge(refA, refB):
            if refA not in perWs and refB not in perWs:
                return cmp_(refA, refB)
            elif refB not in perWs:
                return -1
            elif refA not in perWs:
                return 1
            else:
                return cmp_(perWs[refA]['age'], perWs[refB]['age'])
        sprint('-' * 75)
        wsList = list(set(perWs.keys()).union(set(remind.keys())))
        for wkspace in sorted(wsList, key=cmp_to_key(_byAge)):
            if wkspace:
                sprint(os.path.basename(wkspace) + ':')
            else:
                sprint('Outside of any workspace:')
            for res in ['pass', 'fail']:
                if wkspace in perWs and res in perWs[wkspace]:
                    j = perWs[wkspace][res]
                    sec = int((unow - j.stopTime).total_seconds())
                    tmHour = sec / (60 * 60)
                    sec -= tmHour * 60 * 60
                    tmMin = sec / 60
                    sec -= tmMin * 60
                    diffTime = '%d:%02d:%02d' % (tmHour, tmMin, sec)
                    sprint(
                        '  last %s, \033[97m%s\033[0m ago' %
                        (res, diffTime))
                    sprint('    ' + text_type(j))
            if wkspace in remind:
                sprint('  reminders:')
                for j in remind[wkspace]:
                    sprint('    \033[92m%s\033[0m' % j.reminder)
            sprint('')
        sprint('-' * 75)

    def addDeps(self, fromWhere, thisWs, deps, depSuccess):
        if fromWhere:
            for k in fromWhere:
                depJob = self.getJobMatch(k, thisWs)
                if depJob.key in self.active:
                    doMsg(" - adding dependency:", depJob)
                deps.append(depJob)
                if depSuccess is not None:
                    depSuccess.append(depJob)

    def uidx(self):
        return self.active.uidx()

    def new(self, cmd, isolate, autoJob=False, key=None, reminder=None):
        # pylint: disable=too-many-arguments
        if key and key in self.active.db:
            raise Exception("Active key conflict for key '%s'" % key)
        job = service().db.jobInfo(self.uidx(), key)
        job.isolate = isolate
        job.setCmd(cmd, reminder)
        job.pid = os.getpid()
        job.autoJob = autoJob
        logfile = "___" + job.key + ".log"
        (fp, job.logfile) = tempfile.mkstemp(suffix=logfile,
                                             dir=self.config.logDir)
        job.parent = self
        if not autoJob:
            self.active.lastJob = job.key
        return job, fp

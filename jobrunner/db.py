from __future__ import absolute_import, division, print_function
import anydbm
import datetime
import fcntl
import os
import sys
import tempfile
import time

import simplejson as json
import dateutil.tz

import jobrunner.utils as utils
from .info import JobInfo, encodeJobInfo, decodeJobInfo
from .utils import utcNow, stackDetails, pidDebug, doMsg

NUM_RECENT = 100
PRUNE_NUM = 5000

# pylint: disable=deprecated-lambda


class Database(object):
    schemaVersion = "2"
    SV = '_schemaVersion_'
    LASTKEY = '_lastKey_'
    ITEMCOUNT = '_itemCount_'
    RECENT = '_recentItems_'
    IDX = '_currentIndex_'
    LASTJOB = '_lastJob_'
    CHECKPOINT = '_checkPoint_'
    special = [SV, LASTKEY, LASTJOB, ITEMCOUNT, RECENT, IDX, CHECKPOINT]

    def __init__(self, parent, config, dbFile):
        self.config = config
        self.dbFile = self.config.dbDir + dbFile
        self._parent = parent

    @property
    def db(self):
        db = anydbm.open(self.dbFile, 'c')
        if (self.SV not in db or
                db[self.SV] != self.schemaVersion):
            db.close()
            db = anydbm.open(self.dbFile, 'n')
            db[self.SV] = self.schemaVersion
            db[self.LASTKEY] = ""
            db[self.LASTJOB] = ""
            db[self.ITEMCOUNT] = "0"
            db[self.CHECKPOINT] = ""
        return db

    def filterJobs(self, k):
        return k not in self.special

    def iteritems(self):
        return self.db.iteritems()

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
            return json.loads(self.db[self.CHECKPOINT])
        except KeyError:
            return datetime.datetime.utcfromtimestamp(0)
        except EOFError:
            return datetime.datetime.utcfromtimestamp(0)

    def setCheckpoint(self, val):
        if isinstance(val, str):
            if val.strip() == ".":
                checkpoint = utcNow()
            else:
                checkpoint = dateutil.parser.parse(val)
                if not checkpoint.tzinfo:
                    checkpoint = checkpoint.replace(
                        tzinfo=dateutil.tz.tzlocal())
        elif isinstance(val, datetime.datetime):
            if not checkpoint.tzinfo:
                checkpoint = checkpoint.replace(tzinfo=dateutil.tz.tzlocal())
        else:
            raise ValueError(
                "Expecting either a string or a datetime.datetime")
        utc = checkpoint.astimezone(dateutil.tz.tzutc())
        self.db[self.CHECKPOINT] = json.dumps(utc)

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
        return filter(self.filterJobs, self.db.keys())

    def recentGet(self):
        if self.RECENT in self.db:
            return json.loads(self.db[self.RECENT])
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
            pidDebug(self.dbFile, "[%s]" % key, "=", repr(value))
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
        return "DB %d '%s' ver %s" % (
            self.count, self.dbFile, self.db[self.SV])

    def uidx(self):
        if self.IDX in self.db:
            cur = json.loads(self.db[self.IDX])
        else:
            cur = 0
        self.db[self.IDX] = json.dumps(cur + 1)
        return cur


class Jobs(object):
    # pylint: disable=too-many-public-methods
    def __init__(self, config, plugins):
        self.config = config
        self.plugins = plugins
        self.active = Database(self, config, 'activeJobs')
        self.inactive = Database(self, config, 'inactiveJobs')
        self.lockFp = None
        self.displayPending = set()

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

    def lock(self):
        self.debugPrint("< LOCK DB")
        assert self.lockFp is None
        self.lockFp = open(self.config.lockFile, 'a')
        fcntl.flock(self.lockFp, fcntl.LOCK_EX)
        self.debugPrint("<< LOCKED")

    def unlock(self):
        self.debugPrint("< UNLOCK DB")
        self.lockFp.close()
        self.lockFp = None

    def prune(self, exceptNum=None):
        allJobs = []
        db = self.inactive
        for k in db.keys():
            j = db[k]
            if isinstance(j, str):
                del db[k]
            elif j.key != k:
                print("Warning, key mismatch k=%s job key=%s" % (repr(k),
                                                                 repr(j.key)))
                print(j.detail("vvv"))
                del db[k]
            else:
                allJobs.append(j)
        allJobs.sort()
        limit = PRUNE_NUM if exceptNum is None else exceptNum
        if len(allJobs) > limit:
            for j in allJobs[: -1 * limit]:
                if self.config.verbose:
                    print("Prune '%s'" % j.key)
                j.removeLog(self.config.verbose)
                del self.inactive[j.key]

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
                if job in ['Not a valid entry', 'None']:
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
        print(fmt % "", job)
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
            curPane = os.environ.get('TMUX_PANE', None)
            if curPane:
                jobList = [
                    j for j in jobList if j.matchEnv(
                        'TMUX_PANE', curPane)]
        return jobList

    def listDb(self, db, limit, filterWs=False, filterPane=False, useCp=False):
        # pylint: disable=too-many-arguments
        jobList = self.filterJobs(db, limit, filterWs, filterPane, useCp)
        hasDeps = False
        for job in jobList:
            if job.depends:
                hasDeps = self.walkDepTree(
                    lambda j, d: d == 1, db, job.depends, 1)
        if hasDeps:
            print(utils.SPACER)
        for job in jobList:
            if self.config.verbose:
                print(job.detail(self.config.verbose[1:]))
            else:
                if db is self.active:
                    print(job)
                    if job.depends:
                        self.printDepTree(db, job.depends)
                    if hasDeps:
                        print(utils.SPACER)
                else:
                    print(job)
        if not jobList:
            print("(None)")

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
        for job in jobList:
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

    def listActive(self, thisWs, pane, useCp):
        self.listDb(
            self.active,
            None,
            filterWs=thisWs,
            filterPane=pane,
            useCp=useCp)

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
            jobList = filter(
                lambda x: self.filterJobsWith(x, skipReminders=skipReminders),
                self.getDbSorted(self.active, None, filterWs=thisWs))
            if not jobList:
                jobList = filter(
                    lambda x: self.filterJobsWith(
                        x, skipReminders=skipReminders),
                    self.getDbSorted(self.inactive, None, filterWs=thisWs))
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

    @staticmethod
    def wait(func, desc, verbose, _timeout=None):
        if func():
            return
        if verbose:
            print("\nWaiting for %s" % desc)
        while not func():
            time.sleep(1)
            if verbose:
                sys.stdout.write(".")
                sys.stdout.flush()

    def waitFor(self, job, verbose):
        self.wait(
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
        self.wait(lambda: self.inactiveKey(key), 'inactive key "%s"' % key,
                  verbose)

    def showJobList(self, joblist, tag, clearLen):
        timestr = datetime.datetime.now().strftime(utils.DATETIME_FMT)
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
            print("%s" % timestr + details + " " * clearNum)

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
            nonReminder = filter(lambda j: j.reminder is None, activeJobList)
            activeReminder = filter(lambda j: j.reminder and j.startTime,
                                    activeJobList)
            newJobs = [j.key for j in nonReminder]
            finishedJobs = set(curJobs) - set(newJobs)
            curJobs = newJobs
            sys.stdout.write("\r")
            now = datetime.datetime.now()
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

                if timeNow >= resUpd + resUpdInterval:
                    resUpd = timeNow
                    resource = self.getResources()

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
            time.sleep(1)

    def activityWindow(self, options):
        # pylint: disable=too-many-locals,too-many-branches
        if options.activity:
            activityLevel = len(options.activity)
        else:
            activityLevel = 1
        today = []
        tnow = datetime.datetime.now()
        unow = utcNow()
        perWs = {}
        remind = {}
        for k in self.active.keys():
            j = self.active[k]
            if not j.reminder:
                continue
            if not j.startTime:
                print('not started yet', str(j), j.workspace)
                continue
            remind.setdefault(j.workspace, []).append(j)
        for k in self.inactive.keys():
            j = self.inactive[k]
            if j in ['Not a valid entry', 'None']:
                continue
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
                return cmp(refA, refB)
            elif refB not in perWs:
                return -1
            elif refA not in perWs:
                return 1
            else:
                return cmp(perWs[refA]['age'], perWs[refB]['age'])
        print('-' * 75)
        wsList = list(set(perWs.keys()).union(set(remind.keys())))
        for wkspace in sorted(wsList, cmp=_byAge):
            if wkspace:
                print(os.path.basename(wkspace) + ':')
            else:
                print('Outside of any workspace:')
            for res in ['pass', 'fail']:
                if wkspace in perWs and res in perWs[wkspace]:
                    j = perWs[wkspace][res]
                    sec = int((unow - j.stopTime).total_seconds())
                    tmHour = sec / (60 * 60)
                    sec -= tmHour * 60 * 60
                    tmMin = sec / 60
                    sec -= tmMin * 60
                    diffTime = '%d:%02d:%02d' % (tmHour, tmMin, sec)
                    print(
                        '  last %s, \033[97m%s\033[0m ago' %
                        (res, diffTime))
                    print('    ' + str(j))
            if wkspace in remind:
                print('  reminders:')
                for j in remind[wkspace]:
                    print('    \033[92m%s\033[0m' % j.reminder)
            print('')
        print('-' * 75)

    def addDeps(self, fromWhere, thisWs, deps, depSuccess):
        if fromWhere:
            for k in fromWhere:
                depJob = self.getJobMatch(k, thisWs)
                if depJob.key in self.active:
                    doMsg("adding dependency:", depJob)
                deps.append(depJob)
                if depSuccess is not None:
                    depSuccess.append(depJob)

    def uidx(self):
        return self.active.uidx()

    def new(self, cmd, isolate, autoJob=False, key=None, reminder=None):
        # pylint: disable=too-many-arguments
        if key and key in self.active.db:
            raise Exception("Active key conflict for key '%s'" % key)
        job = JobInfo(self.uidx(), key)
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

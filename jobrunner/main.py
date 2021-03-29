#!/usr/bin/env python
from __future__ import absolute_import, division, print_function

import argparse
import errno
import hashlib
import os
from subprocess import PIPE, CalledProcessError, Popen, check_call, check_output
import sys
import tempfile
import time

import dateutil.parser
import dateutil.tz
import six

import jobrunner.logging

from .argparse import addArgumentParserBaseFlags, baseParsedArgsToArgList
from .binutils import binDescriptionWithStandardFooter
from .config import Config
from .plugins import Plugins
from .service import service
from .service.registry import registerServices
from .utils import (
    DATETIME_FMT,
    MOD_STATE,
    SPACER_EACH,
    STOP_ABORT,
    STOP_DEPFAIL,
    STOP_DONE,
    STOP_STOP,
    autoDecode,
    doMsg,
    keyEscape,
    lockedSection,
    quiet,
    robotInfo,
    setQuiet,
    showMsgs,
    sprint,
)

_DEBUG_LOG_FILE_NAME = "jobrunner-debug"
LOG = jobrunner.logging.getLogger(__name__)


def main(args=None):
    # pylint: disable=too-many-branches
    # pylint: disable=too-many-locals
    # pylint: disable=too-many-statements
    plugins = Plugins()
    MOD_STATE.plugins = plugins

    registerServices()

    options = parseArgs(args)
    config = Config(options)
    jobs = service().db.jobs(config, plugins)

    jobrunner.logging.setup(
        config.logDir,
        _DEBUG_LOG_FILE_NAME,
        debug=options.debug)
    LOG.debug("starting with args %s", options)
    LOG.debug("python: %s", sys.version)
    jobs.lock()
    maybeHandleNonExecOptions(options, jobs)
    maybeHandleNonExecWriteOptions(options, jobs)

    setQuiet(options.quiet)

    doIsolate = options.isolate
    cmd = []
    if options.mail:
        oneJob = jobs.getJobMatch(options.mail[0], options.tw)
        subj = '[job-status] '
        if len(options.mail) > 1:
            subj += "Multiple jobs: %s" % repr(options.mail)
        else:
            subj += str(oneJob)
        cmd.extend([config.mailProgram, '-s', subj])
        if options.cc:
            for ccAddr in options.cc:
                if '@' not in ccAddr:
                    ccAddr += '@' + config.mailDomain
                cmd += ['-c', ccAddr]
        if config.mailProgram == 'chatmail':
            # Special case for built-in chatmail, which should inherit any of the
            # base args given to job, such as which rc file to use, etc.
            cmd.extend(baseParsedArgsToArgList(args or sys.argv, options))
        cmd.append(options.to)
    elif options.command:
        bashCmd = postCommand(options.command)
        cmd = ['bash', '-c', bashCmd]
    elif options.retry:
        oldJob = jobs.getJobMatch(options.retry, options.tw)
        if os.getcwd() != oldJob.pwd:
            sprint(
                "NOTE: Changing directory to '%s' to retry job." %
                oldJob.pwd)
            os.chdir(oldJob.pwd)
        sprint("retry job '%s'" % oldJob.cmdStr)
        cmd = oldJob.cmd
        if oldJob.isolate:
            doIsolate = oldJob.isolate
    elif options.reminder:
        cmd = None
    elif options.program:
        cmd = [options.program]
        if options.args:
            cmd = cmd + postCommand(options.args)
    elif options.wait:
        pass
    else:
        sprint(jobs.getLog(key=None, thisWs=options.tw, skipReminders=True))
        jobs.unlock()
        sys.exit(0)

    deps = []
    depSuccess = []
    depWait = []
    jobs.addDeps(options.blocked_by, options.tw, deps, None)
    jobs.addDeps(options.wait, options.tw, deps, depWait)
    jobs.addDeps(options.blocked_by_success, options.tw, deps, depSuccess)
    jobs.addDeps(options.mail, options.tw, deps, None)

    if depWait:
        rc = waitForDep(depWait, options, jobs)
        jobs.unlock()
        sys.exit(rc)

    job, fd = jobs.new(cmd, doIsolate, autoJob=options.auto_job,
                       key=options.key, reminder=options.reminder)
    job.genPersistKey()
    jobs.active[job.key] = job

    scriptName = os.path.basename(sys.argv[0])
    if scriptName == 'job' and not options.foreground:
        jobs.unlock()
        childPid = os.fork()
        if childPid > 0:
            LOG.info("forked child %d, close %d", childPid, fd)
            os.close(fd)
            rc = 0
            if options.monitor:
                rc = monitorForkedJob(job, jobs)
            sys.exit(rc)
        os.setsid()
        job.pid = os.getpid()
        jobs.lock()
        jobs.active[job.key] = job

    if options.mail:
        job.mailJob = True

    aborted = False
    mailDeps = []
    if deps:
        try:
            job.blocked(jobs)
            while deps:
                job.setDependencies(jobs, deps)
                dep = deps.pop(0)
                LOG.debug("wait for dep %s", dep)
                jobs.waitFor(dep, options.verbose)
                mailDeps.append(dep)
        except KeyboardInterrupt:
            sprint("\ninterrupted")
            aborted = True
        finally:
            LOG.debug("unlocked %s", job, exc_info=1)
            job.unblocked(jobs)
            job.setDependencies(jobs, None)
    if aborted:
        LOG.debug("aborted %s", job)
        job.stop(jobs, STOP_ABORT)
        jobs.unlock()
        sys.exit(-1)

    for oldJob in depSuccess:
        k = oldJob.permKey
        jobs.waitInactive(k, options.verbose)
        j = jobs.inactive[k]
        if j.rc != 0:
            out = "Dependent job failed: {}\n".format(j)
            out += "{}\n".format(j.detail("vvv"))
            LOG.debug("out %s", out)
            os.write(fd, out.encode('utf-8'))
            job.stop(jobs, STOP_DEPFAIL)
            sprint("\nDependent job failed: %s" % j)
            sprint("key: %s" % job.key)
            sprint("return code: %d" % j.rc)
            jobs.unlock()
            sys.exit(j.rc)

    job.start(jobs)
    LOG.debug("started job %s", job)
    if cmd is None and options.reminder is not None:
        sprint("reminder: '%s'" % options.reminder)
        jobs.unlock()
        sys.exit(0)

    if options.mail:
        # Collect output files as attachments from dep jobs
        tmp = tempfile.NamedTemporaryFile(prefix='jobInfo-')
        options.input = tmp.name
        mailSize = 0

        # Remove 'to' address temporarily
        lastArg = cmd.pop(-1)
        for j in mailDeps:
            depJob = jobs.inactive[j.permKey]
            safeWrite(tmp, depJob.detail(options.verbose))
            safeWrite(tmp, "\n" + SPACER_EACH + "\n")
            lines = autoDecode(check_output(['tail', '-n20', depJob.logfile]))
            safeWrite(tmp, lines)
            safeWrite(tmp, SPACER_EACH + "\n")
            safeWrite(tmp, "\n")
            try:
                stat = os.stat(depJob.logfile)
            except OSError:
                continue
            if (mailSize + stat.st_size * 4 / 3) < 8 * 1024 * 1024:
                mailSize += stat.st_size
                cmd += ['-a', depJob.logfile]
        tmp.flush()
        cmd.append(lastArg)

    runJob(cmd, options, jobs, job, fd, doIsolate)


def waitForDep(depWait, options, jobs):
    while depWait:
        dep = depWait.pop(0)
        k = dep.permKey
        try:
            jobs.waitFor(dep, options.verbose)
            jobs.waitInactive(k, options.verbose)
        except KeyboardInterrupt:
            LOG.info("return 1 after interrupt", exc_info=True)
            return 1

        j = jobs.inactive[k]
        if j.rc != 0:
            sprint("\nDependent job failed: %s" % j)
            sprint("key: %s" % j.key)
            sprint("return code: %d" % j.rc)
            return j.rc
    return 0


def monitorForkedJob(job, jobs):
    monitorCmd = ["tail", "-n+0", "-f", job.logfile]
    monitor = Popen(monitorCmd, stdout=sys.stdout, stderr=sys.stdout)
    try:
        active = True
        rc = 0
        while active:
            LOG.debug("monitoring, sleep 0.5")
            with lockedSection(jobs):
                active = job.key in jobs.active.db
                rc = None
                if not active:
                    rc = jobs.inactive[job.key].rc
            time.sleep(0.5)
            LOG.debug('active %s, rc %r', active, rc)
        return rc
    except KeyboardInterrupt:
        LOG.debug('KeyboardInterrupt')
        sprint("\n(Stop monitoring): {}".format(job))
    except BaseException:
        LOG.info('exception', exc_info=1)
        raise
    finally:
        LOG.debug('terminate monitor subprocess')
        monitor.terminate()
        monitor.kill()
        monitor.wait()
    return 0


removeChars = frozenset("\x1B\x0d")


def safeWrite(fd, value):
    value = six.text_type(value)
    value = ''.join(c for c in value if c not in removeChars)
    fd.write(value.encode('utf-8'))


def postCommand(cmd):
    return cmd


def finish(job, rc):
    LOG.debug("finish %s", job)
    doMsg("key:", job.key)
    LOG.debug("first doMsg is OK %s", job)
    doMsg("return code:", rc)
    robotInfo("finish", {"key": job.key}, {"rc": rc})
    if rc != 0 and quiet():
        LOG.debug("calling showMsgs for job %s", job)
        showMsgs()


DESC = binDescriptionWithStandardFooter("""
job - Job runner with logging

Note: `.` is a common alias for any `key` argument and refers to the most recently
started job.


Examples:
    # Run `sleep 5` in the background
    $ job sleep 5

    # Run `ls` only if last job passed.
    $ job -B. ls

    # Runs `ls` when last job finishes (pass / fail)
    $ job -b. ls

    # Monitor job execution
    $ job -W

    # Retry a job
    $ job --retry ls
""")


class ExitCode(Exception):
    def __init__(self, rc):
        super(ExitCode, self).__init__(self, rc)
        self.rc = rc


def addNonExecOptions(op):
    op.add_argument("--count", action="store_true",
                    help="Count jobs in inactive database")
    op.add_argument(
        "-l",
        "--list",
        action="append_const",
        const=True,
        help="List active jobs, -ll to include active reminders")
    op.add_argument("--dot", action='store_true',
                    help='Show dependency graph for active jobs')
    op.add_argument("--png", action='store_true',
                    help='Create dependency graph svg for active jobs in '
                    '~%s/output/job.svg' % os.getenv('USER'))
    op.add_argument("--svg", action='store_true',
                    help='Create dependency graph png for active jobs in '
                    '~%s/output/job.svg' % os.getenv('USER'))
    op.add_argument("-L", "--list-inactive", action="store_true",
                    help="List inactive jobs")
    op.add_argument("-W", "--watch", action="store_true",
                    help="Watch for any job acitvity")
    op.add_argument("-s", "--show", metavar="KEY", action="append",
                    help="Get details for job specified by KEY")
    op.add_argument("-K", "--last-key", action="store_true",
                    help="Get the latest key")
    op.add_argument("--index", "-n", action='append', type=int,
                    help='Get log file name, by index, from recent jobs')
    op.add_argument("--pid", metavar="KEY", action="append",
                    help="Show pstree for job specified by KEY")
    op.add_argument("-g", "--get-log", metavar="KEY", action="append",
                    help="Get log file name for job specified by KEY")
    op.add_argument("-G", "--get-all-logs", action="store_true",
                    help="Get all log file names for running jobs")
    op.add_argument("--info", action="store_true", help="Show DB info")
    op.add_argument(
        "--int",
        metavar="KEY",
        action="append",
        help='Kill (INT) the specified job using its process group ID')
    op.add_argument(
        "--stop",
        metavar="KEY",
        action="append",
        help="Force job status 'stopped' for the job specified by KEY")
    op.add_argument("--delete", metavar="KEY", action="append",
                    help="Remove inactive job specified by KEY")
    op.add_argument("--prune", action="store_true",
                    help="Prune inactive jobs and log files")
    op.add_argument(
        "--prune-except",
        type=int,
        metavar='COUNT',
        action="store",
        help="Prune inactive jobs and log files, leaving the "
        "last COUNT jobs in the database.")
    op.add_argument("-p", "--since-checkpoint", action="store_true",
                    help="Only display jobs since the checkpoint")
    op.add_argument("-P", "--set-checkpoint", metavar="TIME", action="store",
                    help="Set checkpoint for -p.  Use '.' for now")
    op.add_argument(
        "-a",
        "--activity",
        action="append_const",
        const=1,
        help="Display recent activity per workspace (repeat multiple "
        "times for a longer activity window)")
    op.add_argument("-A", "--activity-window", metavar='HOURS', type=float,
                    action="store",
                    help="Display recent activity per workspace within the "
                    "specified window")


def handleNonExecOptions(options, jobs):
    # pylint: disable=too-many-branches
    # pylint: disable=too-many-locals
    # pylint: disable=too-many-return-statements
    # pylint: disable=too-many-statements
    if options.list:
        includeReminders = len(options.list) > 1
        jobs.listActive(thisWs=options.tw, pane=options.tp,
                        useCp=options.since_checkpoint,
                        includeReminders=includeReminders)
        return True
    elif options.dot or options.png or options.svg:
        dot = jobs.makeDot(
            jobs.active,
            jobs.inactive,
            filterWs=options.tw,
            filterPane=options.tp,
            useCp=options.since_checkpoint)
        LOG.debug("dot: %s", dot)
        if options.dot:
            sprint(dot)
        else:
            fName = '~%s/output/job.svg' % os.getenv('USER')
            ofile = os.path.expanduser(fName)
            cmd = ['dot', '-Tsvg', '-o', ofile]
            proc = Popen(cmd, stdout=PIPE, stderr=PIPE, stdin=PIPE)
            stdout, stderr = proc.communicate(input=dot.encode('utf-8'))
            if stdout.strip() or stderr.strip():
                raise ExitCode(stdout + stderr)
            sprint('Saved output to', fName)
        return True
    elif options.list_inactive:
        jobs.listInactive(options.tw, options.tp, options.since_checkpoint)
        return True
    elif options.count:
        sprint(jobs.countInactive())
        return True
    elif options.get_all_logs:
        logs = []
        for job in jobs.filterJobs(jobs.active, limit=30,
                                   filterWs=options.tw,
                                   filterPane=options.tp,
                                   useCp=options.since_checkpoint):
            logs.append(job.logfile)
        sprint(" ".join(logs))
        return True
    elif options.get_log:
        logs = []
        for key in options.get_log:
            logs.append(jobs.getLog(key, options.tw))
        sprint(" ".join(logs))
        return True
    elif options.show:
        for k in options.show:
            j = jobs.getJobMatch(k, options.tw)
            sprint(j.detail(options.verbose))
        return True
    elif options.pid:
        for key in options.pid:
            try:
                showPstreeForKey(key, jobs, options)
            except KeyError as error:
                sprint("Error:", error)
        return True
    elif options.last_key:
        sprint(jobs.inactive.lastKey)
        return True
    elif options.index:
        logs = []
        for index in options.index:
            logs.append(jobs.getLogByIndex(index, options.tw))
        sprint(" ".join(logs))
        jobs.unlock()
        sys.exit(0)
    elif options.info:
        sprint(jobs.active)
        sprint(jobs.inactive)
        return True
    elif options.activity or options.activity_window:
        jobs.activityWindow(options)
        return True
    else:
        return False


def handleNonExecWriteOptions(options, jobs):
    # pylint: disable=too-many-branches
    # pylint: disable=too-many-return-statements
    if options.stop:
        errors = []
        for k in options.stop:
            try:
                j = jobs.getJobMatch(k, options.tw)
                if j.key in jobs.active:
                    sprint("Stopping job:", j)
                    j.stop(jobs, STOP_STOP)
                else:
                    errors.append(j.key)
            except KeyError:
                errors.append(k)
        if errors:
            raise ExitCode("Jobs not active: {}".format(", ".join(errors)))
        return True
    elif options.int:
        done = False
        for k in options.int:
            j = jobs.getJobMatch(k, options.tw)
            j.killPgrp(jobs)
            done = True
        if not done:
            raise ExitCode(1)
        return True
    elif options.done:
        for k in options.done:
            j = jobs.getJobMatch(k, options.tw)
            if j.reminder:
                sprint('Done with reminder: "%s"' % j.reminder)
            j.stop(jobs, STOP_DONE)
        return True
    elif options.prune:
        jobs.prune()
        return True
    elif options.prune_except:
        jobs.prune(options.prune_except)
        return True
    elif options.delete:
        for k in options.delete:
            j = jobs.inactive[k]
            sprint("Delete job '%s'" % j.key)
            j.removeLog(verbose=True)
            del jobs.inactive[j.key]
        return True
    elif options.set_checkpoint:
        jobs.active.checkpoint = options.set_checkpoint
        jobs.inactive.checkpoint = options.set_checkpoint
        cpUtc = jobs.active.checkpoint
        local = cpUtc.astimezone(dateutil.tz.tzlocal())
        sprint("Set checkpoint: ", local.strftime(DATETIME_FMT))
        return True
    elif options.watch:
        try:
            jobs.watchActivity()
        except KeyboardInterrupt:
            sprint("")
            sprint("Exit on user interrupt")
            raise ExitCode(1)  # pylint: disable=bad-option-value, raise-missing-from
        return True
    else:
        return False


def pidOk(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError as error:
        if error.errno == errno.EPERM:
            # Operation not permitted
            return True
        elif error.errno == errno.ESRCH:
            # No such process
            return False
        else:
            raise
    return True


class Pstree(object):
    def __init__(self, text):
        self.text = autoDecode(text).strip() if text else None
        self.errors = []


def getPstree(pid):
    pstree = Pstree(None)
    try:
        return Pstree(check_output(['pstree', '-alpg', str(pid)]))
    except (OSError, CalledProcessError) as error:
        pstree.errors.append(error)
    try:
        return Pstree(check_output(['ps', '-fp', str(pid)]))
    except (OSError, CalledProcessError) as error:
        pstree.errors.append(error)
    return pstree


def showPstreeForKey(key, jobs, options):
    j = jobs.getJobMatch(key, options.tw)
    sprint("==============================================")
    sprint(j)
    if pidOk(j.pid):
        pstree = getPstree(j.pid)
        if not pstree.errors:
            sprint(pstree.text)
        elif pidOk(j.pid):
            sprint("Errors getting PID info for", j.pid)
            for err in pstree.errors:
                sprint(err)
        else:
            sprint("PID not found", j.pid)
    else:
        sprint("PID not found", j.pid)
    sprint("==============================================")


def parseArgs(args=None):
    if args is None:
        prog = sys.argv[0]
        args = sys.argv[1:]
    else:
        prog = None

    op = argparse.ArgumentParser(
        prog=os.path.basename(prog),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=DESC)
    op.add_argument("program", nargs='?')
    op.add_argument("args", nargs=argparse.REMAINDER)

    addArgumentParserBaseFlags(op, _DEBUG_LOG_FILE_NAME)

    out = op.add_mutually_exclusive_group()
    out.add_argument('--robot-format', dest='quiet', action='store_const',
                     const='robot', help='Output job execution formatted for robots')
    out.add_argument('-q', '--quiet', action='store_const', const='quiet',
                     help='Do not print any messages')
    execMode = op.add_mutually_exclusive_group()
    execMode.add_argument("-f", "--foreground", action="store_true",
                          help="Do not fork, run in foreground.")
    execMode.add_argument("--monitor", action="store_true",
                          help="Run in the background, but monitor output")
    op.add_argument("-c", "--command", metavar="CMD",
                    help="Specify complete bash command to execute "
                    "(argument to bash -c)")
    op.add_argument("--retry", metavar="KEY", action="store",
                    help="Retry job specified by KEY")
    op.add_argument(
        "-r",
        "--reminder",
        metavar="REMINDER",
        action="store",
        help="Specify a reminder job (must be stopped manually with "
        "--done).")
    op.add_argument(
        "--done",
        metavar="KEY",
        action="append",
        help="Mark reminder as 'done' for the reminder specified by "
        "KEY")
    op.add_argument(
        "-k",
        "--key",
        metavar="KEY",
        help="Specify job key to use (must be unique among active jobs)")
    op.add_argument(
        "-m",
        "--mail",
        metavar="KEY",
        action="append",
        help="Send mail on job completion for job specified by KEY")
    op.add_argument("-t", "--to", metavar="ADDRESS",
                    help="Specify 'to' address for mail notification "
                    "(default=%(default)s)",
                    default=os.getenv('USER'))
    op.add_argument("--cc", metavar="ADDRESS", action="append",
                    help="Specify 'CC' address for mail notification")
    op.add_argument("--tw", "--this-workspace", action="store_true",
                    help="Filter by jobs in this workspace")
    op.add_argument("--tp", "--this-pane", action="store_true",
                    help="Filter by jobs in this tmux pane")
    op.add_argument(
        "-b",
        "--blocked-by",
        metavar="KEY",
        action="append",
        help="Specify that this job depends on the job specified by "
        "KEY")
    op.add_argument(
        "-B",
        "--blocked-by-success",
        metavar="KEY",
        action="append",
        help="Specify that this job depends on the successful execution "
        "of the job specified by KEY")
    op.add_argument("-w", "--wait", metavar="KEY", action="append",
                    help="Wait for job specified by KEY to finish")
    op.add_argument(
        "-i",
        "--isolate",
        action="store_true",
        help="Isolate execution of the job using netns and isolate")
    op.add_argument("--input", metavar="FILENAME", action="store",
                    help="Specify input file (default='%(default)s')",
                    default="/dev/null")
    op.add_argument("--auto-job", action="store_true",
                    help="Specify that this job is an automatic job (not user "
                    "initiated).  This will stop it from being picked up as "
                    "the implicit job key '.' when using -B")

    addNonExecOptions(op)

    options = op.parse_args(args)
    return options


def maybeHandle(options, jobs, handler):
    try:
        handled = handler(options, jobs)
        if handled:
            jobs.unlock()
            sys.exit(0)
    except ExitCode as exitCode:
        jobs.unlock()
        sys.exit(exitCode.rc)


def maybeHandleNonExecOptions(options, jobs):
    maybeHandle(options, jobs, handleNonExecOptions)


def maybeHandleNonExecWriteOptions(options, jobs):
    maybeHandle(options, jobs, handleNonExecWriteOptions)


def handleIsolate(cmd):
    isolateName = keyEscape(" ".join(cmd))
    if len(isolateName) > 45:
        hashVal = hashlib.new('md5')
        for char in cmd:
            hashVal.update(char.encode("raw_unicode_escape"))
        isolateName = hashVal.hexdigest()[:16]
    netnsd = ['isolate', '-n', isolateName]
    netnsd += cmd
    LOG.info('Isolating command %r -> %r', cmd, netnsd)
    return netnsd


def runJob(cmd, options, jobs, job, fd, doIsolate):
    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-statements
    LOG.info("execute: %s", job.cmdStr)
    doMsg("execute:", job.cmdStr)
    robotInfo("execute", {"key": job.key}, {"command": job.cmdStr})
    fpIn = open(options.input, "r")
    rc = -1
    if doIsolate:
        cmd = handleIsolate(cmd)

    try:
        jobs.unlock()
        LOG.debug("starting check_call()")
        rc = check_call(cmd, stdin=fpIn, stdout=fd, stderr=fd)
        LOG.debug("check_call() => rc=%d", rc)
    except KeyboardInterrupt:
        LOG.debug("KeyboardInterrupt", exc_info=1)
        sprint("\ninterrupted")
        rc = -1
    except OSError as err:
        LOG.debug("OSError %s", err, exc_info=1)
        rc = -1 * err.errno
        sprint(err, file=open(job.logfile, 'a'))
    except CalledProcessError as err:
        LOG.debug("CalledProcessError %s", err, exc_info=1)
        rc = err.returncode
    except Exception:
        LOG.debug("General exception", exc_info=1)
        rc = -1
        raise
    finally:
        LOG.debug("stop job, it has finished %s", job, exc_info=1)
        jobs.lock()
        LOG.debug("locked DB, writing 'stop' status rc=%d", rc)
        job.stop(jobs, rc)
        os.fsync(fd)
        LOG.debug("locked DB, writing 'finish' status rc=%d", rc)
        finish(job, rc)
        jobs.unlock()
        LOG.debug("unlocked, should now exit rc=%d", rc)
    LOG.debug("exit rc=%d", rc)
    sys.exit(rc)


if __name__ == "__main__":
    main()

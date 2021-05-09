#!/usr/bin/env python

import argparse
from collections import namedtuple
import contextlib
import os
import os.path
import pipes
import re
import shutil
import subprocess
import sys
from typing import Iterable, List

VerInfo = namedtuple("VerInfo", ("version", "lock", "default"))

VERSIONS = (
    VerInfo("2.7", "Pipfile-2.7.lock", False),
    VerInfo("3.8", "Pipfile-3.8.lock", False),
    VerInfo("3.7", "Pipfile.lock", True),
)

PIPCONF = (
    "~/.config/pip/pip.conf",
    "/etc/pip.conf",
    "~/.pip/pip.conf",
)


class ProgError(Exception):
    pass


class UserError(ProgError):
    pass


class TestError(ProgError):
    pass


def assertFileClean(filename: str):
    out = subprocess.check_output(["git", "status", "--porcelain", filename])
    if out:
        raise UserError("File is unclean and will be overwritten: " + filename)


def assertClean(versions: Iterable[VerInfo]):
    for version in versions:
        lockFile = version.lock
        assertFileClean(lockFile)
    assertFileClean("Pipfile")


def resolvePipConf() -> str:
    for confName in PIPCONF:
        if os.access(confName, os.R_OK):
            return confName
    return "/dev/null"


def runDocker(version: VerInfo, cmd: List[str]):
    cmdStr = " ".join(map(pipes.quote, cmd))
    print("+", cmdStr)
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as er:
        raise TestError(
            f"trial failed for version {version.version}; command: \n{cmdStr}"
        ) from er


def execVersion(version: VerInfo, pipConf: str, upgrade: bool):
    baseDir = os.path.join(os.getcwd(), f"docker-{version.version}")
    homeDir = os.path.join(baseDir, "home/me")
    cacheDir = os.path.join(homeDir, ".cache")
    localDir = os.path.join(homeDir, ".local")
    for dirName in (cacheDir, localDir):
        if not os.path.isdir(dirName):
            os.makedirs(dirName)

    with open("Pipfile") as f:
        pipfile = f.read()
    pipfile = re.sub(
        r"^\s*python_version\s*=\s*\S+$",
        f'python_version = "{version.version}"',
        pipfile,
        flags=re.MULTILINE,
    )
    with open("Pipfile", "w") as f:
        f.write(pipfile)

    mounts = [
        (os.getcwd(), "/src"),
        (homeDir, "/home/me"),
        (pipConf, "/etc/pip.conf"),
        (cacheDir, "/home/me/.cache"),
    ]
    envs = [
        ("HOME", "/home/me"),
        ("_NEW_UID", str(os.getuid())),
        ("_NEW_GID", str(os.getgid())),
        ("PIP_INDEX_URL", os.getenv("PIP_INDEX_URL", "")),
    ]
    envs += [("PIPENV_CMD", "update" if upgrade else "sync")]

    dockerCmd = ["docker", "run", "--rm"]
    for mount in mounts:
        dockerCmd += ["-v", ":".join(mount)]
    for env in envs:
        dockerCmd += ["-e", "{}={}".format(*env)]
    dockerCmd += [f"python:{version.version}"]
    dockerCmd += ["/src/test-docker-helper.sh"]
    runDocker(version, dockerCmd)


@contextlib.contextmanager
def pipfileForVersion(version: VerInfo):
    if not version.default:
        shutil.copyfile(version.lock, "Pipfile.lock")
    try:
        yield
    finally:
        if not version.default:
            shutil.copyfile("Pipfile.lock", version.lock)
            subprocess.check_output(["git", "checkout",
                                     "Pipfile", "Pipfile.lock"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--versions",
        metavar="VERSION",
        choices=sorted([v[0] for v in VERSIONS]),
        nargs="*",
        help="specify version(s) to test, select from %(choices)s. "
        "Default is all.",
    )
    ap.add_argument("-U", "--upgrade", action="store_true")
    ap.add_argument("-i", "--ignore-unclean", action="store_true")
    args = ap.parse_args()
    versions: Iterable[VerInfo]

    if args.versions:
        versions = tuple(v for v in VERSIONS if v.version in args.versions)
    else:
        versions = VERSIONS

    print(versions)
    if not args.ignore_unclean:
        assertClean(versions)

    pipConf = resolvePipConf()

    for version in versions:
        with pipfileForVersion(version):
            execVersion(version, pipConf, args.upgrade)


if __name__ == "__main__":
    try:
        main()
    except ProgError as error:
        print("Error:", error)
        sys.exit(1)

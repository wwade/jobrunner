#!/usr/bin/env python

import argparse
import contextlib
from dataclasses import dataclass
import os
import os.path
import pipes
import re
import subprocess
import sys
from typing import Iterable, List, Tuple


@dataclass(frozen=True)
class VerInfo:
    version: str


VERSIONS = (
    VerInfo("3.8"),
    VerInfo("3.9"),
    VerInfo("3.10"),
    VerInfo("3.7"),
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


def mountsForContainer(version: VerInfo, pipConf: str) -> List[Tuple[str, str]]:
    baseDir = os.path.join(os.getcwd(), f"docker-{version.version}")
    homeDir = os.path.join(baseDir, "home/me")
    cacheDir = os.path.join(homeDir, ".cache")
    localDir = os.path.join(homeDir, ".local")
    for dirName in (cacheDir, localDir):
        if not os.path.isdir(dirName):
            os.makedirs(dirName)
    mounts = [
        (os.getcwd(), "/src"),
        (homeDir, "/home/me"),
        (pipConf, "/etc/pip.conf"),
        (cacheDir, "/home/me/.cache"),
    ]
    return mounts


def execVersion(version: VerInfo, pipConf: str, upgrade: bool, cmd: Iterable[str]):

    with open("Pipfile", encoding="utf-8") as f:
        pipfile = f.read()
    pipfile = re.sub(
        r"^\s*python_version\s*=\s*\S+$",
        f'python_version = "{version.version}"',
        pipfile,
        flags=re.MULTILINE,
    )
    with open("Pipfile", "w", encoding="utf-8") as f:
        f.write(pipfile)

    mounts = mountsForContainer(version, pipConf)
    envs = [
        ("HOME", "/home/me"),
        ("_NEW_UID", str(os.getuid())),
        ("_NEW_GID", str(os.getgid())),
        ("PIP_INDEX_URL", os.getenv("PIP_INDEX_URL", "")),
    ]
    envs += [("PIPENV_CMD", "update" if upgrade else "sync")]

    dockerCmd = ["docker", "run", "--rm"]
    if cmd:
        dockerCmd += ["-i", "-t"]
    for mount in mounts:
        dockerCmd += ["-v", ":".join(mount)]
    for env in envs:
        dockerCmd += ["-e", "{}={}".format(*env)]
    dockerCmd += [f"python:{version.version}"]
    dockerCmd += cmd if cmd else ["/src/test-docker-helper.sh"]
    runDocker(version, dockerCmd)


@contextlib.contextmanager
def pipfileForVersion(keepModifiedPipfile: bool):
    try:
        yield
    finally:
        if not keepModifiedPipfile:
            subprocess.check_output(["git", "checkout",
                                     "Pipfile", "Pipfile.lock"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--versions",
        metavar="VERSION",
        choices=sorted([v.version for v in VERSIONS]),
        nargs="*",
        help="specify version(s) to test, select from %(choices)s. "
        "Default is all.",
    )
    ap.add_argument("-U", "--upgrade", action="store_true")
    ap.add_argument("-i", "--ignore-unclean", action="store_true")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    cmd = args.cmd
    if cmd and cmd[0].strip() == "--":
        cmd.pop(0)
    versions: Iterable[VerInfo]

    if args.versions:
        versions = tuple(v for v in VERSIONS if v.version in args.versions)
    else:
        versions = VERSIONS

    print(versions)

    pipConf = resolvePipConf()

    for version in versions:
        with pipfileForVersion(bool(cmd)):
            execVersion(version, pipConf, args.upgrade, cmd)


if __name__ == "__main__":
    try:
        main()
    except ProgError as error:
        print("Error:", error)
        sys.exit(1)

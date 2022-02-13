import logging
from subprocess import CalledProcessError, check_output
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def run(*args: str) -> Optional[str]:
    try:
        return check_output(args, encoding="utf-8").strip()
    except CalledProcessError as err:
        logger.warning("error: %s", err)
        return None


def workspaceProject() -> Tuple[str, bool]:
    head = run("git", "rev-parse", "HEAD")
    if not head:
        return "", False

    top = run("git", "rev-parse", "--show-toplevel")
    return f"{top}:{head}" if top else head, True

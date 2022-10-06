import logging
from typing import Tuple
from unittest import mock

import pytest

from jobrunner.plugins import Plugins

logger = logging.getLogger(__name__)


class Plugin:
    @classmethod
    def load(cls):
        return cls


class PluginAAANoPrio(Plugin):
    @staticmethod
    def workspaceProject() -> Tuple[str, bool]:
        return "lowest", True

    @staticmethod
    def getResources(jobs):
        _ = jobs
        return "[no-prio]"


class PluginBBBLowPrioResources(Plugin):
    @staticmethod
    def workspaceProject() -> Tuple[str, bool]:
        return "lowest", True

    @staticmethod
    def getResources(jobs):
        _ = jobs
        return "[low-prio]"


class PluginZABHighPrioNoProject(Plugin):
    @staticmethod
    def priority():
        return {"": 0}

    @staticmethod
    def workspaceProject() -> Tuple[str, bool]:
        raise NotImplementedError


class PluginZAAHighestPrio(Plugin):
    @staticmethod
    def priority():
        return {"": 0}

    @staticmethod
    def workspaceProject() -> Tuple[str, bool]:
        return "highest", True


class PluginMMMLowPrio(Plugin):
    @staticmethod
    def priority():
        return {"": 1000}

    @staticmethod
    def workspaceProject() -> Tuple[str, bool]:
        return "low", True


@pytest.mark.parametrize(
    ["plugins", "workspaceProject", "resources"],
    [
        (
            {PluginAAANoPrio, PluginMMMLowPrio, PluginZAAHighestPrio},
            "highest",
            "[no-prio]",
        ),
        (
            {PluginAAANoPrio, PluginMMMLowPrio, PluginZABHighPrioNoProject},
            "low",
            "[no-prio]",
        ),
        (
            {PluginAAANoPrio, PluginBBBLowPrioResources, PluginMMMLowPrio},
            "low",
            "[no-prio][low-prio]",
        ),
    ]
)
def testPluginPriorities(plugins, workspaceProject, resources):
    with mock.patch("jobrunner.plugins.get_plugins") as gp, \
            mock.patch("importlib.import_module") as im, \
            mock.patch("socket.gethostname", return_value="xxx"):
        im.return_value = []
        gp.return_value = plugins

        p = Plugins()

        logger.info("only PluginNoPrio implements getResources()")
        assert resources == p.getResources(None)

        logger.info("no plugins implement workspaceIdentity()")
        assert "xxx" == p.workspaceIdentity()

        logger.info("all plugins implement workspaceProject()")
        assert (workspaceProject, True) == p.workspaceProject()

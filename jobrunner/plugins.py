"""
This module implements the plugin contract.

Plugin modules need to be registered using the wwade.jobrunner entrypoint. Modules
that are registered as such can implement any of the functions:

    def priority():
        return {"getResources": 100, "workspaceProject": 10, "workspaceIdentity": 10}

    def getResources(jobs):
        return "some string"

    def workspaceIdentity():
        return "home/tmp-dir"

    def workspaceProject():
        # If the current context has a notion of a "project name", return the project
        # name as well as a bool True to indicate that the plugin is authoritative.
        return "the current project name", True

All of these functions are optional. If the plugin cannot provide a sensible value
for the current execution then it should raise NotImplementedError so that the next
plugin at a possibly lower priority will get called instead.
"""
import importlib
import logging
from operator import attrgetter
import pkgutil
import socket
from typing import Tuple
import warnings

import jobrunner.plugin

from .compat import get_plugins

logger = logging.getLogger(__name__)
PRIO_LOWEST = 1 << 31
PRIO_HIGHEST = 0


def gethostname() -> str:
    return socket.gethostname()


class Plugins(object):
    def __init__(self):
        plugins = {plug.load() for plug in get_plugins("wwade.jobrunner")}
        deprecatedPlugins = {
            importlib.import_module("jobrunner.plugin.{}".format(name))
            for _, name, _
            in pkgutil.iter_modules(jobrunner.plugin.__path__)
        }
        if deprecatedPlugins:
            warnings.warn("Found old-style plugins in jobrunner.plugin: %r. "
                          "Convert to entry_point 'wwade.jobrunner'" % list(
                              deprecatedPlugins),
                          DeprecationWarning)
        plugins |= deprecatedPlugins
        self.plugins = list(sorted(plugins, key=attrgetter("__name__")))
        logger.debug("all plugins: %r", [p.__name__ for p in self.plugins])
        self._prio = {}
        for plugin in self.plugins:
            if hasattr(plugin, "priority"):
                self._prio[plugin.__name__] = plugin.priority()

    def _pluginCalls(self, func, *args, **kwargs):
        prio = {}
        for plugin in self.plugins:
            if hasattr(plugin, func):
                pluginPrioMap = self._prio.get(plugin.__name__, {})
                pval = pluginPrioMap.get(func, pluginPrioMap.get("", PRIO_LOWEST))
                prio.setdefault(pval, []).append(plugin)

        if not prio:
            return

        for prio, plugins in sorted(prio.items()):
            for plugin in plugins:
                name = plugin.__name__
                try:
                    result = getattr(plugin, func)(*args, **kwargs)
                    logger.debug("%r: yield plugin %s => %r", prio, name, result)
                    yield result
                except NotImplementedError:
                    logger.debug("%r: plugin %s NotImplementedError", prio, name)
                    continue

    def getResources(self, jobs):
        return "".join(self._pluginCalls("getResources", jobs))

    def workspaceIdentity(self):
        for ret in self._pluginCalls("workspaceIdentity"):
            if ret:
                return ret
        logger.debug("using gethostname as fallback for workspaceIdentity")
        return gethostname()

    def workspaceProject(self) -> Tuple[str, bool]:
        """
        If the current context has a notion of a "project name", return the project
        name as well as a bool True to indicate that the plugin is authoritative.
        """
        for (ret, ok) in self._pluginCalls("workspaceProject"):
            if ok:
                return ret, ok
        return "", False

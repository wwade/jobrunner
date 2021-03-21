from __future__ import absolute_import, division, print_function

import importlib
import pkgutil
import warnings

import jobrunner.plugin

from .compat import metadata


class Plugins(object):
    def __init__(self):
        self.plugins = {
            plug.load() for plug in metadata.entry_points().get(
                'wwade.jobrunner', [])}
        deprecatedPlugins = {
            importlib.import_module('jobrunner.plugin.{}'.format(name))
            for finder, name, ispkg
            in pkgutil.iter_modules(jobrunner.plugin.__path__)
        }
        if deprecatedPlugins:
            warnings.warn("Found old-style plugins in jobrunner.plugin: %r. "
                          "Convert to entry_point 'wwade.jobrunner'" % list(
                              deprecatedPlugins),
                          DeprecationWarning)
        self.plugins |= deprecatedPlugins

    def _plugDo(self, which, *args, **kwargs):
        for plugin in self.plugins:
            if hasattr(plugin, which):
                getattr(plugin, which)(*args, **kwargs)

    def getResources(self, jobs):
        ret = ""
        for plugin in self.plugins:
            if hasattr(plugin, 'getResources'):
                ret += plugin.getResources(jobs)
        return ret

    def workspaceIdentity(self):
        for plugin in self.plugins:
            if hasattr(plugin, 'workspaceIdentity'):
                ret = plugin.workspaceIdentity()
                if ret:
                    return ret
        return ""

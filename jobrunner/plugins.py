from __future__ import absolute_import, division, print_function

import importlib
import pkgutil

import jobrunner.plugin


class Plugins(object):
    def __init__(self):
        self.plugins = {
            name: importlib.import_module('jobrunner.plugin.{}'.format(name))
            for finder, name, ispkg
            in pkgutil.iter_modules(jobrunner.plugin.__path__)
        }

    def _plugDo(self, which, *args, **kwargs):
        for plugin in self.plugins.values():
            if hasattr(plugin, which):
                getattr(plugin, which)(*args, **kwargs)

    def getResources(self, jobs):
        ret = ""
        for plugin in self.plugins.values():
            if hasattr(plugin, 'getResources'):
                ret += plugin.getResources(jobs)
        return ret

    def workspaceIdentity(self):
        for plugin in self.plugins.values():
            if hasattr(plugin, 'workspaceIdentity'):
                ret = plugin.workspaceIdentity()
                if ret:
                    return ret
        return ""

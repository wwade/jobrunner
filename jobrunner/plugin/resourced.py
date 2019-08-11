from __future__ import absolute_import, division, print_function
import os
try:
    from ResourceManager.Client import Client
    PLUGIN_ENABLED = True
except BaseException:
    PLUGIN_ENABLED = False


class PlugState(object):
    def __init__(self):
        self._resClient = None

    def resClient(self):
        if self._resClient is None:
            resHost = os.environ.get('RESOURCE_HOST', 'localhost')
            self._resClient = Client(host=resHost)
        return self._resClient


STATE = PlugState()


def getResources(_jobs):
    if not PLUGIN_ENABLED:
        return ""
    res = STATE.resClient().resources()
    avail = res['available']
    total = res['total']
    return ", cores: %.1f/%.0f, mem: %u/%u" % (
        avail['cores'], total['cores'], avail['rammb'], total['rammb'])

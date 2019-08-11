from __future__ import absolute_import, division, print_function

import os
import ConfigParser


RC_FILE_HELP = """\
Sample rcfile:
    [mail]
    program = mail
    domain = example.com
"""


def _getConfig(cfgParser, section, option, defaultValue=None):
    if not cfgParser.has_section(section):
        return defaultValue
    if not cfgParser.has_option(section, option):
        return defaultValue
    return cfgParser.get(section, option)


class Config(object):
    def __init__(self, options):
        stateDir = options.stateDir
        self.options = options
        self._dbDir = os.path.expanduser(stateDir) + "/db/"
        self._logDir = os.path.expanduser(stateDir) + "/log/"
        self._lockFile = os.path.expanduser(stateDir) + "/db/.lockdb"
        self.debugLevel = options.debugLevel if options.debugLevel else []

        rcFile = os.path.expanduser(options.rcFile)
        cfgParser = ConfigParser.ConfigParser()
        cfgParser.read(rcFile)
        self._mailDomain = _getConfig(
            cfgParser, "mail", "domain", os.environ.get('HOSTNAME'))
        self._mailProgram = _getConfig(cfgParser, "mail", "program", "mail")

    @property
    def verbose(self):
        return self.options.verbose

    @staticmethod
    def checkDir(dirName):
        if not os.access(dirName, os.W_OK | os.X_OK | os.R_OK):
            os.makedirs(dirName)
        return dirName

    @property
    def dbDir(self):
        return self.checkDir(self._dbDir)

    @property
    def logDir(self):
        return self.checkDir(self._logDir)

    @property
    def lockFile(self):
        self.checkDir(os.path.dirname(self._lockFile))
        return self._lockFile

    @property
    def mailDomain(self):
        return self._mailDomain

    @property
    def mailProgram(self):
        return self._mailProgram

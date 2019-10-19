from __future__ import absolute_import, division, print_function

import ConfigParser
import os

RC_FILE_HELP = """\
Sample rcfile:
    [mail]
    program = mail
    domain = example.com
    [ui]
    watch reminder = full|summary  # default=summary
"""

WATCH_REMINDER_FULL = "full"
WATCH_REMINDER_SUMMARY = "summary"
WATCH_REMINDER_OPTIONS = (
    WATCH_REMINDER_FULL,
    WATCH_REMINDER_SUMMARY,
)
WATCH_REMINDER_DEFAULT = WATCH_REMINDER_SUMMARY


def _getConfig(cfgParser, section, option, defaultValue=None):
    if not cfgParser.has_section(section):
        return defaultValue
    if not cfgParser.has_option(section, option):
        return defaultValue
    return cfgParser.get(section, option)


class ConfigError(Exception):
    pass


class Config(object):
    # pylint: disable=too-many-instance-attributes
    validConfig = {
        'mail': {'domain', 'program'},
        'ui': {'watch reminder'},
    }

    def _validateConfigParser(self, cfgParser):
        cfgSections = set(cfgParser.sections())
        unknownSections = cfgSections - set(self.validConfig.keys())
        if unknownSections:
            raise ConfigError(
                "RC file has unknown configuration sections: {}".format(
                    ", ".join(sorted(unknownSections))))
        for section in cfgSections:
            cfgValues = set(cfgParser.options(section))
            unknownOptions = cfgValues - self.validConfig[section]
            if unknownOptions:
                raise ConfigError(
                    "RC file has unknown configuration options in "
                    "section \"{}\": {}".format(section,
                                                ", ".join(sorted(unknownOptions))))

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
            cfgParser, "mail", "domain", os.getenv('HOSTNAME'))
        self._mailProgram = _getConfig(cfgParser, "mail", "program", "mail")
        self._uiWatchReminder = _getConfig(
            cfgParser, "ui", "watch reminder", WATCH_REMINDER_DEFAULT)
        if self._uiWatchReminder not in WATCH_REMINDER_OPTIONS:
            raise ConfigError(
                "RC file has invalid \"ui.watch reminder\" setting {}.  Valid "
                "options: {}".format(self._uiWatchReminder,
                                     ", ".join(WATCH_REMINDER_OPTIONS)))

        self._validateConfigParser(cfgParser)

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

    @property
    def uiWatchReminderSummary(self):
        return self._uiWatchReminder == WATCH_REMINDER_SUMMARY

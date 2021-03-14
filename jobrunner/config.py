from __future__ import absolute_import, division, print_function

import os
import sys

import six

RC_FILE_HELP = """\
Sample rcfile:
    [mail]
    program = mail
    domain = example.com
    [ui]
    watch reminder = full|summary  # default=summary
    [chatmail]
    at all = all|none|no id # default=none
    reuse threads = true|false # default true
    [chatmail.google-chat-userhooks]
    user1 = https://chat.googleapis.com/v1/spaces/...
    [chatmail.google-chat-userids]
    user1 = <long integer> # retrieve this using your browser inspector on an \
existing mention of this user
"""


class ConfigEnum(object):
    __slots__ = (
        'defaultName',
        '_enumVals',
    )

    def __init__(self, default, **enumVals):
        self._enumVals = enumVals
        assert default in enumVals
        self.defaultName = default
        for enumName in enumVals:
            assert enumName not in self.__slots__

    def names(self):
        return six.iterkeys(self._enumVals)

    def values(self):
        return six.itervalues(self._enumVals)

    @property
    def defaultVal(self):
        return self._enumVals[self.defaultName]

    def __getattr__(self, attr):
        assert attr != '_enumVals'
        if attr in self._enumVals:
            return self._enumVals[attr]
        else:
            return object.__getattribute__(self, attr)


WATCH_REMINDER_FULL = "full"
WATCH_REMINDER_SUMMARY = "summary"

WATCH_REMINDER = ConfigEnum(
    'SUMMARY',  # default
    FULL=WATCH_REMINDER_FULL,
    SUMMARY=WATCH_REMINDER_SUMMARY,
)

CHATMAIL_AT_ALL = ConfigEnum(
    'NONE',  # default
    ALL='all',
    NONE='none',
    NO_ID='no id',
)


def _getConfig(cfgParser, section, option, defaultValue=None):
    if not cfgParser.has_section(section):
        return defaultValue
    if not cfgParser.has_option(section, option):
        return defaultValue
    return cfgParser.get(section, option)


def _getEnumConfig(cfgParser, section, option, enum):
    optionVal = _getConfig(
        cfgParser, section, option, enum.defaultVal)
    if optionVal not in list(enum.values()):
        raise ConfigError(
            "RC file has invalid \"{section}.{option}\" setting {optionVal}.  Valid "
            "options: {allowedVals}".format(
                section=section,
                option=option,
                optionVal=optionVal,
                allowedVals=", ".join(list(enum.values()))))

    return optionVal


def _getDictConfig(cfgParser, section):
    options = {}
    if not cfgParser.has_section(section):
        return options
    for option in cfgParser.options(section):
        roomUri = _getConfig(cfgParser, section, option, None)
        options[option] = roomUri
    return options


def _getBoolConfig(cfgParser, section, option, default):
    val = _getConfig(cfgParser, section, option, None)
    if val is None:
        return default
    if val.lower() == 'true':
        return True
    elif val.lower() == 'false':
        return False
    else:
        raise ConfigError(
            "RC file has invalid \"{section}.{option}\" setting {optionVal}.  Valid "
            "options: true, false".format(
                section=section,
                option=option,
                optionVal=val))


class ConfigError(Exception):
    pass


_VAR_OPTIONS = object()


class Config(object):
    # pylint: disable=too-many-instance-attributes
    validConfig = {
        'mail': {'domain', 'program'},
        'chatmail': {'at all', 'reuse threads'},
        'chatmail.google-chat-userhooks': _VAR_OPTIONS,
        'chatmail.google-chat-userids': _VAR_OPTIONS,
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
            validSectionConfig = self.validConfig[section]
            if validSectionConfig is not _VAR_OPTIONS:
                assert isinstance(validSectionConfig, set)
                unknownOptions = cfgValues - validSectionConfig
                if unknownOptions:
                    raise ConfigError(
                        "RC file has unknown configuration options in "
                        "section \"{}\": {}".format(
                            section, ", ".join(sorted(unknownOptions))))

    def __init__(self, options):
        stateDir = options.stateDir
        self.options = options
        self._dbDir = os.path.expanduser(stateDir) + "/db/"
        self._logDir = os.path.expanduser(stateDir) + "/log/"
        self._cacheDir = os.path.expanduser(stateDir) + "/cache/"
        self._lockFile = os.path.expanduser(stateDir) + "/db/.lockdb"
        self.debugLevel = options.debugLevel if options.debugLevel else []

        rcFile = os.path.expanduser(options.rcFile)
        if sys.version_info.major >= 3:
            cfgParser = six.moves.configparser.RawConfigParser()
        else:
            cfgParser = six.moves.configparser.ConfigParser()
        cfgParser.read(rcFile)
        self._mailDomain = _getConfig(
            cfgParser, "mail", "domain", os.getenv('HOSTNAME'))
        self._mailProgram = _getConfig(cfgParser, "mail", "program", "mail")

        self._uiWatchReminder = _getEnumConfig(
            cfgParser, 'ui', 'watch reminder', WATCH_REMINDER)

        self._chatmailAtAll = _getEnumConfig(
            cfgParser, 'chatmail', 'at all', CHATMAIL_AT_ALL)
        self._chatmailReuseThreads = _getBoolConfig(
            cfgParser, 'chatmail', 'reuse threads', True)
        self._gChatUserHooks = _getDictConfig(
            cfgParser, 'chatmail.google-chat-userhooks')
        self._gchatUserIds = _getDictConfig(
            cfgParser, 'chatmail.google-chat-userids')

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
    def cacheDir(self):
        return self.checkDir(self._cacheDir)

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

    @property
    def chatmailAtAll(self):
        return self._chatmailAtAll

    @property
    def chatmailReuseThreads(self):
        return self._chatmailReuseThreads

    def gChatUserHook(self, user):
        return self._gChatUserHooks.get(user)

    def gChatUserId(self, user):
        return self._gchatUserIds.get(user)

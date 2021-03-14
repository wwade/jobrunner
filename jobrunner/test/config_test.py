from __future__ import absolute_import, division, print_function

import os
import tempfile
import unittest

from mock import MagicMock, patch
import six

from jobrunner import config

from .helpers import resetEnv

HOSTNAME = 'host.example.com'
HOME = '/home/me'

EXAMPLE_RCFILE = """\
[ui]
watch reminder = full
[chatmail]
at all = all
reuse threads = false
[chatmail.google-chat-userhooks]
user1 = https://chat.googleapis.com/v1/spaces/something1
user2 = https://chat.googleapis.com/v1/spaces/something2
[chatmail.google-chat-userids]
user1 = 1234
[mail]
program=mail-program
domain=ex.com
"""

BAD_SECTION = """\
[unknown]
"""


def setUpModule():
    resetEnv()
    os.environ['HOSTNAME'] = HOSTNAME
    os.environ['HOME'] = HOME


class TestMixin(object):
    @staticmethod
    def config(tempFp=None):
        options = MagicMock()
        options.rcFile = tempFp.name if tempFp else '/a-file-does-not-exist.cfg'
        options.stateDir = '~/x'
        return config.Config(options)


class TestRcParser(unittest.TestCase, TestMixin):
    @patch('os.makedirs')
    def testStateDir(self, _makedirs):
        cfgObj = self.config()
        self.assertEqual(os.path.join(HOME, 'x/db/'), cfgObj.dbDir)

    # pylint: disable-msg=too-many-arguments
    def assertCfg(self, cfgObj, domain=HOSTNAME,
                  program='mail', reminderSummary=True,
                  chatmailAtAll='none', chatmailReuseThreads=True,
                  gChatUserHookDict=None, gChatUserIdDict=None):
        self.assertEqual(domain, cfgObj.mailDomain)
        self.assertEqual(program, cfgObj.mailProgram)
        self.assertEqual(reminderSummary, cfgObj.uiWatchReminderSummary)
        self.assertEqual(chatmailAtAll, cfgObj.chatmailAtAll)
        self.assertEqual(chatmailReuseThreads, cfgObj.chatmailReuseThreads)

        if gChatUserHookDict is None:
            gChatUserHookDict = {}
        for user, hook in six.iteritems(gChatUserHookDict):
            self.assertEqual(hook, cfgObj.gChatUserHook(user))

        if gChatUserIdDict is None:
            gChatUserIdDict = {}
        for user, uid in six.iteritems(gChatUserIdDict):
            self.assertEqual(uid, cfgObj.gChatUserId(user))

    def testNoFile(self):
        cfgObj = self.config()
        self.assertCfg(cfgObj)

    def testEmptyFile(self):
        with tempfile.NamedTemporaryFile(mode='w') as tempFp:
            tempFp.flush()
            cfgObj = self.config(tempFp)
            self.assertCfg(cfgObj)

    def testConfigured(self):
        with tempfile.NamedTemporaryFile(mode='w') as tempFp:
            tempFp.write(EXAMPLE_RCFILE)
            tempFp.flush()
            cfgObj = self.config(tempFp)
            self.assertCfg(
                cfgObj, domain='ex.com', program='mail-program',
                reminderSummary=False, chatmailAtAll='all',
                chatmailReuseThreads=False,
                gChatUserHookDict={
                    'user1': 'https://chat.googleapis.com/v1/spaces/something1',
                    'user2': 'https://chat.googleapis.com/v1/spaces/something2',
                },
                gChatUserIdDict={'user1': '1234'},
            )

    def testConfigureSummary(self):
        with tempfile.NamedTemporaryFile(mode='w') as tempFp:
            tempFp.write("[ui]\nwatch reminder=summary\n")
            tempFp.flush()
            cfgObj = self.config(tempFp)
            self.assertCfg(cfgObj, reminderSummary=True)


class TestMalformedRcFile(unittest.TestCase, TestMixin):
    def testBadSection(self):
        with tempfile.NamedTemporaryFile(mode='w') as tempFp:
            tempFp.write(EXAMPLE_RCFILE + BAD_SECTION)
            tempFp.flush()
            pattern = r'unknown configuration sections: unknown'
            with six.assertRaisesRegex(self, config.ConfigError, pattern):
                self.config(tempFp)

    def testBadOption(self):
        with tempfile.NamedTemporaryFile(mode='w') as tempFp:
            tempFp.write(EXAMPLE_RCFILE + "\n" + "xyz = foo\n")
            tempFp.flush()
            pattern = r'unknown configuration options in section "mail": xyz'
            with six.assertRaisesRegex(self, config.ConfigError, pattern):
                self.config(tempFp)

    def testReminderBadOption(self):
        with tempfile.NamedTemporaryFile(mode='w') as tempFp:
            tempFp.write("[ui]\nwatch reminder=foo\n")
            tempFp.flush()
            pattern = (
                r'RC file has invalid "ui.watch reminder" setting foo.\s*' +
                r'Valid options: (full, summary|summary, full)'
            )
            with six.assertRaisesRegex(self, config.ConfigError, pattern):
                self.config(tempFp)

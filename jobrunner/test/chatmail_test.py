from __future__ import absolute_import, division, print_function

import re
from unittest import TestCase

from mock import ANY, MagicMock, call, patch
import requests
import six

from jobrunner.config import CHATMAIL_AT_ALL
from jobrunner.mail import chat
from jobrunner.test.helpers import capturedOutput

# pylint: disable-msg=protected-access


@patch("jobrunner.mail.chat.requests", new=MagicMock(requests))
class ChatPostTest(TestCase):
    def testGoodRequest(self):
        retMock = MagicMock(['json'])
        chat.requests.post = MagicMock(return_value=retMock)
        retMock.json.return_value = {"thread": {"name": "somethread"}}
        self.assertEqual(
            chat._postToGChat("foo", "https://something"),
            "somethread")

    def testBadRequestReturn(self):
        retMock = MagicMock(['json'])
        chat.requests.post = MagicMock(return_value=retMock)

        retValues = [
            {"thread": None},
            {},
            {"thread": {}},
        ]
        for retVal in retValues:
            retMock.json.return_value = retVal
            self.assertEqual(
                chat._postToGChat("foo", "https://something"),
                None)


@patch("jobrunner.mail.chat.ThreadIdCache._read", new=MagicMock())
@patch("jobrunner.mail.chat.ThreadIdCache._write", new=MagicMock())
class ChatThreadIdCacheTest(TestCase):
    def test1(self):
        chat.ThreadIdCache._read.return_value = {}

        threadCache = chat.ThreadIdCache("/foo")
        threadCache._read.return_value = {}

        val = threadCache.get("https://somehook")
        self.assertIsNone(val)


@patch("jobrunner.mail.chat.requests", new=object)
@patch("jobrunner.mail.chat._postToGChat")
@patch("jobrunner.mail.chat.Config", spec=chat.Config)
@patch("jobrunner.mail.chat.ThreadIdCache._read")
@patch("jobrunner.mail.chat.ThreadIdCache._write")
@patch('jobrunner.mail.chat.sys.stdin')
class ChatTest(TestCase):
    class Mocks(object):
        def __init__(self, testArgs):
            (
                self.chatStdin,
                self.threadCacheWrite,
                self.threadCacheRead,
                self.configCls,
                self.postToGChat,
            ) = testArgs

            self._doBaseSetup()

        def _doBaseSetup(self):
            self.threadCacheRead.return_value = {}
            self.chatStdin.isatty.return_value = True

        def reset(self):
            self.postToGChat.reset_mock()
            self.threadCacheRead.reset_mock()
            self.threadCacheWrite.reset_mock()

            self._doBaseSetup()

    def assertMultilineRegexpMatches(self, text, regexp):
        six.assertRegex(self, text, re.compile(regexp, flags=re.S))

    def assertPostTextMatchesRegexp(self, regexp, callIdx=0):
        # pylint: disable-msg=no-member
        text = chat._postToGChat.call_args[callIdx][0]
        self.assertMultilineRegexpMatches(text, regexp)

    def testRequestSafetySanity(self, *_):
        with self.assertRaises(AttributeError):
            chat.requests.post()

    def testBasicCall(self, *mockArgs):
        mocks = ChatTest.Mocks(mockArgs)
        hook = "https://somehook"
        mocks.configCls().gChatUserHook.return_value = hook

        chat.main(['user1'])

        mocks.postToGChat.assert_called_once_with(ANY, hook, threadId=None)
        self.assertPostTextMatchesRegexp('NO SUBJECT')

    def testBasicCallWithOptions(self, *mockArgs):
        mocks = ChatTest.Mocks(mockArgs)
        hook = "https://somehook"

        mocks.configCls().gChatUserHook.return_value = hook

        with patch("jobrunner.mail.chat.open", create=True) as openMock:
            # Mock inFile from -f option
            openMock().__enter__().read.return_value = "a bunch of\ntext."
            openMock.reset_mock()
            ret = chat.main(['-s', 'My subject', '-c', 'user3', '-c', 'user4',
                             '-a', 'attachfile.txt',
                             '-f', 'mytext.txt', 'user1', 'user2'])
            openMock.assert_called_once_with('mytext.txt')

        self.assertEqual(ret, 0)
        mocks.postToGChat.assert_called_once_with(ANY, hook, threadId=None)
        self.assertPostTextMatchesRegexp(
            r'My subject.*a bunch of\ntext.*attachfile.txt')

    def testPipeContent(self, *mockArgs):
        mocks = ChatTest.Mocks(mockArgs)
        hook = "https://somehook"

        for tty in [True, False]:
            mocks.reset()
            mocks.configCls().gChatUserHook.return_value = hook

            mocks.chatStdin.isatty.return_value = tty
            mocks.chatStdin.read.return_value = "a bunch of\ntext"
            ret = chat.main(['-s', 'My subject', 'user1'])

            self.assertEqual(ret, 0)
            mocks.postToGChat.assert_called_once_with(ANY, hook, threadId=None)
            self.assertPostTextMatchesRegexp(
                r'\*My subject\*' + (r'\s*$' if tty else r'.*a bunch of\ntext'))

    def testCallWithMultipleHooks(self, *mockArgs):
        mocks = ChatTest.Mocks(mockArgs)
        hooks = {
            "user1": "https://somehook1",
            "user2": "https://somehook2",
            "user3": "https://somehook3",
            "user4": "https://somehook1",  # Shared with user1
        }
        # pylint: disable-msg=unnecessary-lambda
        mocks.configCls().gChatUserHook = lambda k: hooks.get(k)

        ret = chat.main(['-s', 'My subject', '-c', 'user3', '-c', 'user4',
                         'user1', 'user2'])

        self.assertEqual(ret, 0)
        calls = [call(ANY, hook, threadId=None)
                 for hook in set(hooks.values())]
        self.assertEqual(mocks.postToGChat.call_count, len(calls))
        mocks.postToGChat.assert_has_calls(calls, any_order=True)

    def testCallWithMissingHook(self, *mockArgs):
        mocks = ChatTest.Mocks(mockArgs)
        hook = "https://somehook"
        # pylint: disable-msg=unnecessary-lambda
        mocks.configCls().gChatUserHook = lambda k: {"user1": hook}.get(k)

        with capturedOutput() as (_, err):
            ret = chat.main(['-s', 'My subject', '-c', 'user3', '-c', 'user4',
                             'user1', 'user2'])

        self.assertEqual(ret, 1)
        self.assertEqual(mocks.postToGChat.call_count, 0)
        self.assertMultilineRegexpMatches(err.getvalue(),
                                          r"No Google Chat hook for user[234]")

    def testReuseThreads(self, *mockArgs):
        hook = "https://somehook"
        threadId = "athreadId"

        def _runTest(retThreadId, reuseThreads):
            mocks = ChatTest.Mocks(mockArgs)
            mocks.reset()
            mocks.configCls().gChatUserHook.return_value = hook
            mocks.threadCacheRead.return_value = {
                hook: threadId, "anotherhook": "x"}
            mocks.postToGChat.return_value = retThreadId

            ret = chat.main(([] if reuseThreads else ['-T']) +
                            ['-s', 'My subject', 'user1'])

            self.assertEqual(ret, 0)
            mocks.postToGChat.assert_called_once_with(
                ANY, hook,
                threadId=threadId if reuseThreads else None)
            if threadId == retThreadId:
                self.assertEqual(mocks.threadCacheWrite.call_count, 0)
            else:
                mocks.threadCacheWrite.assert_called_once_with(
                    {hook: retThreadId, "anotherhook": "x"})

        _runTest(threadId, True)
        _runTest("a new thread", True)
        _runTest(threadId, False)
        _runTest("a new thread", False)

    def testUserTags(self, *mockArgs):
        hook = "https://somehook"

        def _runTest(atAllConfig, userIdDict, expectAtAll=False):
            mocks = ChatTest.Mocks(mockArgs)
            mocks.reset()
            mocks.configCls().gChatUserHook.return_value = hook
            mocks.configCls().gChatUserId = lambda user: userIdDict[user]
            mocks.configCls().chatmailAtAll = atAllConfig

            users = list(sorted(userIdDict))

            ret = chat.main(['-s', 'My subject'] + users)

            self.assertEqual(ret, 0)
            mocks.postToGChat.assert_called_once_with(ANY, hook, threadId=None)
            pattern = r'\*My subject\*'
            tags = []
            if expectAtAll:
                tags.append('<users/all>')

            for user in users:
                if userIdDict[user]:
                    tags.append('<users/%s>' % userIdDict[user])
                else:
                    tags.append('@' + user)

            pattern = ' '.join(tags) + ' ' + pattern

            self.assertPostTextMatchesRegexp(pattern)

        noUsersWithId = {'user1': None, 'user2': None}
        someUsersWithId = {'user1': '1234', 'user2': None}
        allUsersWithId = {'user1': '1234', 'user2': '5678'}

        for userDict in [noUsersWithId, someUsersWithId, allUsersWithId]:
            _runTest(CHATMAIL_AT_ALL.ALL, userDict, expectAtAll=True)

        for userDict in [noUsersWithId, someUsersWithId, allUsersWithId]:
            _runTest(CHATMAIL_AT_ALL.NONE, userDict, expectAtAll=False)

        _runTest(CHATMAIL_AT_ALL.NO_ID, noUsersWithId, expectAtAll=True)
        _runTest(CHATMAIL_AT_ALL.NO_ID, someUsersWithId, expectAtAll=True)
        _runTest(CHATMAIL_AT_ALL.NO_ID, allUsersWithId, expectAtAll=False)

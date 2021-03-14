#!/usr/bin/env python

from __future__ import absolute_import, print_function

import argparse
from collections import defaultdict
import json
import os
import sys

import requests
import six

from jobrunner.argparse import addArgumentParserBaseFlags
from jobrunner.binutils import binDescriptionWithStandardFooter
from jobrunner.config import CHATMAIL_AT_ALL, Config

DESC = binDescriptionWithStandardFooter("""
chatmail - A mail/mailx-like chat wrapper provided with `job`

Currently supports:
Google Chat webhooks

For each user you wish to be able to send notifications to, add a webhook for that
user into the rc file (format shown below).
If you want the notification to add a user-specific mention, the user id for that
user will also need to be provided in the rc file. Otherwise, the 'at all'
configuration can be used to add an @all to the message instead.

The message body is accepted through the standard in, or a file (using -f).

to-addr and -c currently operate identically.
""")

_DEBUG_LOG_FILE_NAME = "chatmail-debug"


class ThreadIdCache(object):
    def __init__(self, cacheDir):
        self._cacheFile = os.path.join(cacheDir, 'chatmail.json')

    def _read(self):
        try:
            with open(self._cacheFile, 'r') as cacheFile:
                return json.load(cacheFile)
        except IOError:
            return {}

    def _write(self, data):
        with open(self._cacheFile, 'w') as cacheFile:
            return json.dump(data, cacheFile)

    def get(self, key):
        return self._read().get(key)

    def put(self, key, value):
        data = self._read()
        if data.get(key) != value:
            data[key] = value
            self._write(data)

    def remove(self, key):
        data = self._read()
        if key in data:
            del data[key]
            self._write(data)


class PostError(Exception):
    pass


def _postToGChat(text, uri, threadId=None):
    payload = {
        'text': text,
    }
    headers = {
        'Content-Type': 'application/json; charset=UTF-8',
    }
    if threadId:
        payload['thread'] = {'name': threadId}
    ret = requests.post(uri, json=payload, headers=headers)
    try:
        return ret.json()['thread']['name']
    except (KeyError, TypeError):
        return None


def _getUserAtTokens(users, config):
    usersAreMissingIds = False
    userTokensOrNames = []
    for user in sorted(users):
        userId = config.gChatUserId(user)
        if userId is None:
            userTokensOrNames.append("@" + user)
            usersAreMissingIds = True
        else:
            userTokensOrNames.append("<users/%s>" % userId)

    atAll = False
    if config.chatmailAtAll == CHATMAIL_AT_ALL.ALL:
        atAll = True
    elif config.chatmailAtAll == CHATMAIL_AT_ALL.NO_ID and usersAreMissingIds:
        atAll = True

    userAts = []
    if atAll:
        userAts.append("<users/all>")
    userAts.extend(userTokensOrNames)
    return userAts


def _getMessageBody(opts):
    bodyText = ''
    if opts.inFile:
        with open(opts.inFile) as inFile:
            bodyText = inFile.read()
    elif not sys.stdin.isatty():
        bodyText = sys.stdin.read()

    msgBody = ""
    if bodyText:
        msgBody += '\n```' + bodyText + '```'
    if opts.attachment:
        msgBody += "\nSee " + " ".join(opts.attachment)

    return msgBody


def parseArgs(args=None):
    if args is None:
        prog = sys.argv[0]
        args = sys.argv[1:]
    else:
        prog = None

    # pylint: disable=invalid-name
    ap = argparse.ArgumentParser(
        prog=os.path.basename(prog) if prog else None,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=DESC)
    addArgumentParserBaseFlags(ap, _DEBUG_LOG_FILE_NAME)

    ap.add_argument('-s', dest='subject')
    ap.add_argument('-c', dest='cc', action='append', default=[])
    ap.add_argument('-a', dest='attachment', action='append', default=[])
    ap.add_argument('-f', dest='inFile', action='store')
    ap.add_argument('-T', '--new-thread', action='store_true',
                    help='Do not re-use the previous chat thread for each hook')
    ap.add_argument('toAddr', metavar='to-addr', nargs='+')

    return ap.parse_args(args)


OK = 0
ERROR = 1


def main(args=None):
    opts = parseArgs(args=args)
    config = Config(opts)

    threadCache = ThreadIdCache(config.cacheDir)

    subject = "*%s*" % (opts.subject or "NO SUBJECT")
    msgBody = _getMessageBody(opts)

    users = set(opts.toAddr) | set(opts.cc)
    hooksToUsers = defaultdict(list)
    for user in users:
        hook = config.gChatUserHook(user)
        if hook is None:
            print("No Google Chat hook for", user, file=sys.stderr)
            return ERROR
        hooksToUsers[hook].append(user)

    for hook, users in six.iteritems(hooksToUsers):
        userAts = _getUserAtTokens(users, config)

        subjectAndAts = " ".join(userAts + [subject])
        msg = subjectAndAts + msgBody

        threadId = (threadCache.get(hook)
                    if not opts.new_thread and config.chatmailReuseThreads
                    else None)

        newThreadId = _postToGChat(msg, hook, threadId=threadId)
        threadCache.put(hook, newThreadId)

    return OK


if __name__ == '__main__':
    sys.exit(main())

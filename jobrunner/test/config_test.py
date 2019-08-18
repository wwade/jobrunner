from __future__ import absolute_import, division, print_function

import os
import tempfile
import unittest

from mock import MagicMock, patch

from jobrunner import config

HOSTNAME = 'host.example.com'
HOME = '/home/me'

EXAMPLE_RCFILE = """\
[mail]
program=mail-program
domain=ex.com
"""

BAD_SECTION = """\
[unknown]
"""


def setUpModule():
    os.environ['HOSTNAME'] = HOSTNAME
    os.environ['HOME'] = HOME


class TestMixin(object):
    def config(self, tempFp=None):
        options = MagicMock()
        options.rcFile = tempFp.name if tempFp else '/a-file-does-not-exist.cfg'
        options.stateDir = '~/x'
        return config.Config(options)


class TestRcParser(unittest.TestCase, TestMixin):
    @patch('os.makedirs')
    def testStateDir(self, makedirs):
        cfgObj = self.config()
        self.assertEqual(os.path.join(HOME, 'x/db/'), cfgObj.dbDir)

    def assertCfg(self, cfgObj, domain=HOSTNAME, program='mail'):
        self.assertEqual(domain, cfgObj.mailDomain)
        self.assertEqual(program, cfgObj.mailProgram)

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
            self.assertCfg(cfgObj, domain='ex.com', program='mail-program')


class TestMalformedRcFile(unittest.TestCase, TestMixin):
    def testBadSection(self):
        with tempfile.NamedTemporaryFile(mode='w') as tempFp:
            tempFp.write(EXAMPLE_RCFILE + BAD_SECTION)
            tempFp.flush()
            pattern = r'unknown configuration sections: unknown'
            with self.assertRaisesRegexp(config.ConfigError, pattern):
                self.config(tempFp)

    def testBadOption(self):
        with tempfile.NamedTemporaryFile(mode='w') as tempFp:
            tempFp.write(EXAMPLE_RCFILE + "\n" + "xyz = foo\n")
            tempFp.flush()
            pattern = r'unknown configuration options in section "mail": xyz'
            with self.assertRaisesRegexp(config.ConfigError, pattern):
                self.config(tempFp)

from __future__ import absolute_import, division, print_function

import argparse
import unittest

from jobrunner.argparse import addArgumentParserBaseFlags, baseParsedArgsToArgList


class TestDebugArgument(unittest.TestCase):
    def test_debug_flag_no_argument(self):
        """Test --debug without an argument uses default (True)"""
        parser = argparse.ArgumentParser()
        addArgumentParserBaseFlags(parser, "test-log")
        args = parser.parse_args(["--debug"])
        self.assertTrue(args.debug)

    def test_debug_flag_with_file(self):
        """Test --debug with a file path"""
        parser = argparse.ArgumentParser()
        addArgumentParserBaseFlags(parser, "test-log")
        args = parser.parse_args(["--debug", "/dev/stderr"])
        self.assertEqual("/dev/stderr", args.debug)

    def test_debug_flag_with_custom_file(self):
        """Test --debug with a custom file path"""
        parser = argparse.ArgumentParser()
        addArgumentParserBaseFlags(parser, "test-log")
        args = parser.parse_args(["--debug", "/tmp/my-debug.log"])
        self.assertEqual("/tmp/my-debug.log", args.debug)

    def test_no_debug_flag(self):
        """Test no --debug flag defaults to False"""
        parser = argparse.ArgumentParser()
        addArgumentParserBaseFlags(parser, "test-log")
        args = parser.parse_args([])
        self.assertFalse(args.debug)

    def test_baseParsedArgsToArgList_debug_true(self):
        """Test baseParsedArgsToArgList with debug=True"""
        parser = argparse.ArgumentParser()
        addArgumentParserBaseFlags(parser, "test-log")
        args = parser.parse_args(["--debug"])
        argv = ["--debug"]
        argList = baseParsedArgsToArgList(argv, args)
        self.assertIn("--debug", argList)
        # When debug is True, only --debug should be in the list
        self.assertEqual(["--debug"], argList)

    def test_baseParsedArgsToArgList_debug_with_file(self):
        """Test baseParsedArgsToArgList with debug=/path/to/file"""
        parser = argparse.ArgumentParser()
        addArgumentParserBaseFlags(parser, "test-log")
        args = parser.parse_args(["--debug", "/dev/stderr"])
        argv = ["--debug", "/dev/stderr"]
        argList = baseParsedArgsToArgList(argv, args)
        self.assertEqual(["--debug", "/dev/stderr"], argList)

    def test_baseParsedArgsToArgList_no_debug(self):
        """Test baseParsedArgsToArgList with no debug flag"""
        parser = argparse.ArgumentParser()
        addArgumentParserBaseFlags(parser, "test-log")
        args = parser.parse_args([])
        argv = []
        argList = baseParsedArgsToArgList(argv, args)
        self.assertEqual([], argList)

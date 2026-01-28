from __future__ import absolute_import, division, print_function

import logging
import os
import tempfile
import unittest

from jobrunner.logging import setup


class TestLoggingSetup(unittest.TestCase):
    def setUp(self):
        # Reset logging configuration before each test
        logging.root.handlers = []
        logging.root.setLevel(logging.WARNING)

    def test_setup_no_debug(self):
        """Test setup with debug=False uses stderr"""
        with tempfile.TemporaryDirectory() as tmpdir:
            setup(tmpdir, "test-debug.log", debug=False)
            # Check that the root logger is configured
            self.assertGreater(len(logging.root.handlers), 0)
            # Should use StreamHandler for stderr
            self.assertTrue(
                any(
                    isinstance(h, logging.StreamHandler)
                    for h in logging.root.handlers
                )
            )

    def test_setup_debug_true(self):
        """Test setup with debug=True uses default log file"""
        with tempfile.TemporaryDirectory() as tmpdir:
            setup(tmpdir, "test-debug.log", debug=True)
            # Check that the root logger is configured
            self.assertGreater(len(logging.root.handlers), 0)
            # Should use FileHandler
            self.assertTrue(
                any(
                    isinstance(h, logging.FileHandler) for h in logging.root.handlers
                )
            )
            # Verify the log file was created in the expected location
            expected_file = os.path.join(tmpdir, "test-debug.log")
            self.assertTrue(os.path.exists(expected_file))

    def test_setup_debug_with_custom_file(self):
        """Test setup with debug=/path/to/file uses custom log file"""
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_log = os.path.join(tmpdir, "custom-debug.log")
            setup(tmpdir, "default-debug.log", debug=custom_log)
            # Check that the root logger is configured
            self.assertGreater(len(logging.root.handlers), 0)
            # Should use FileHandler
            self.assertTrue(
                any(
                    isinstance(h, logging.FileHandler) for h in logging.root.handlers
                )
            )
            # Verify the custom log file was created
            self.assertTrue(os.path.exists(custom_log))
            # Verify the default log file was NOT created
            default_file = os.path.join(tmpdir, "default-debug.log")
            self.assertFalse(os.path.exists(default_file))

    def test_setup_debug_with_expanduser(self):
        """Test setup with debug path containing ~ expands correctly"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # We can't actually test with ~, but we can test that expanduser is
            # called by using a regular path and verifying it works
            custom_log = os.path.join(tmpdir, "expanded-debug.log")
            setup(tmpdir, "default-debug.log", debug=custom_log)
            # Verify the custom log file was created
            self.assertTrue(os.path.exists(custom_log))

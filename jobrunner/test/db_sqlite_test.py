from __future__ import absolute_import, division, print_function

import os
from tempfile import NamedTemporaryFile
import unittest

from jobrunner.db.sqlite_db import Sqlite3KeyValueStore, connectDb


class KeyValueStoreTest(unittest.TestCase):
    cached = False

    def store(self, filename=":memory:", ver="0"):
        self.removeStore()
        conn = connectDb(filename)
        store = Sqlite3KeyValueStore("myTable", ver)
        store.setup(conn)
        store.conn = conn
        store.lock()
        self._store = store
        return store

    def removeStore(self):
        if self._store:
            self._store.conn.commit()
            self._store.unlock()
            self._store = None
        return None

    def setUp(self):
        self._store = None

    def tearDown(self):
        if self._store:
            self._store.unlock()
            self._store = None

    def testKeys(self):
        store = self.store()
        self.assertItemsEqual(store.initvals, store.keys())
        store['foo'] = 'value'
        self.assertItemsEqual(list(store.initvals) + ['foo'], store.keys())

    def testLen(self):
        store = self.store()
        store['foo'] = 'value'
        self.assertEqual(len(store.initvals) + 1, len(store))

    def testBasic(self):
        store = self.store()
        self.assertNotIn('foo', store)
        with self.assertRaises(KeyError):
            _ = store['foo']
        store['foo'] = '0'
        self.assertEqual('0', store['foo'])
        store['foo'] = '1'
        self.assertEqual('1', store['foo'])
        self.assertIn('foo', store)
        del store['foo']
        self.assertNotIn('foo', store)

    def testUnicode(self):
        store = self.store()
        key = 'foo'
        val = '\xe2\x94\x80\xe2\x94\x80'.decode('utf-8')
        store[key] = val
        self.assertEqual(val, store[key])
        self.assertIn(key, store)
        del store[key]
        self.assertNotIn(key, store)

    def testWrongVersion(self):
        with NamedTemporaryFile(delete=False) as tempf:
            tempf.close()
        fname = tempf.name
        store = self.store(fname)
        store['foo'] = 'bar'
        store['hello'] = 'goodbye'
        store = self.removeStore()
        store = self.store(fname)
        self.assertEqual('bar', store['foo'])
        self.assertEqual('goodbye', store['hello'])
        del store['hello']
        store = self.removeStore()
        store = self.store(fname)
        self.assertNotIn("hello", store)
        store = self.removeStore()
        store = self.store(fname, "1")
        self.assertNotIn("foo", store)
        os.unlink(fname)

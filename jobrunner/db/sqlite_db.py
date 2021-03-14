from __future__ import absolute_import, division, print_function

from logging import getLogger
import sqlite3

from . import DatabaseBase, DatabaseMeta, JobsBase, resolveDbFile

LOG = getLogger(__name__)


class Sqlite3KeyValueStore(DatabaseMeta):
    def __init__(self, table, schemaVersion):
        self._schemaVersion = schemaVersion
        self._schemaOk = False
        self._dirty = 0
        self.conn = None
        self._table = table
        self._locked = False

    def keys(self):
        cursor = self._doQuery("SELECT key FROM " + self._table)
        return [r[0] for r in cursor.fetchall()]

    def __len__(self):
        query = "SELECT COUNT(key) FROM " + self._table
        cursor = self._doQuery(query)
        return int(cursor.fetchone()[0])

    @property
    def dirty(self):
        return self._dirty

    def _setDirty(self, _key):
        assert self._locked
        self._dirty += 1
        LOG.debug("dirty -> %d", self._dirty)

    def lock(self):
        assert not self._locked
        LOG.debug("set locked")
        self._locked = True

    def unlock(self):
        assert self._locked
        LOG.debug("set unlocked")
        self._locked = False

    def __setitem__(self, key, value):
        self._doQuery(
            "INSERT OR REPLACE INTO " + self._table + " VALUES (?, ?)", key, value)
        self._setDirty(key)

    def __getitem__(self, key):
        cursor = self._doQuery(
            "SELECT value FROM " +
            self._table +
            " WHERE key=?",
            key)
        row = cursor.fetchone()
        if not row:
            raise KeyError(key)
        return row[0]

    def __delitem__(self, key):
        self._doQuery("DELETE FROM " + self._table + " WHERE key=?", key)
        self._setDirty(key)

    def __contains__(self, key):
        cursor = self._doQuery(
            "SELECT value FROM " +
            self._table +
            " WHERE key=?",
            key)
        row = cursor.fetchone()
        return row is not None

    def _cursor(self):
        return self.conn.cursor()

    def _doQuery(self, query, *args):
        assert self._schemaOk
        cursor = self._cursor()
        cursor.execute(query, args or [])
        return cursor

    def _getMeta(self, cursor, key):
        cursor = cursor.execute(
            "SELECT value FROM " + self._table + " WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else None

    def _createNew(self, cursor):
        cursor.execute("DROP TABLE IF EXISTS " + self._table)
        cursor.execute("""
        CREATE TABLE {} (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """.format(self._table))
        for key, value in self.defaultValueGenerator(self._schemaVersion):
            cursor.execute("INSERT INTO " + self._table + " VALUES (?, ?)",
                           (key, value))
        cursor.connection.commit()

    def setup(self, conn):
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM sqlite_master WHERE type='table' AND name=?",
            (self._table,))
        tables = cursor.fetchall()
        if not tables:
            self._createNew(cursor)
        dbVer = self._getMeta(cursor, self.SV)
        if dbVer != self._schemaVersion:
            self._createNew(cursor)
        self._schemaOk = True


class Sqlite3Database(DatabaseBase):
    schemaVersion = "0"

    def __init__(self, parent, config, instanceId, name):
        # pylint: disable=too-many-arguments
        super(Sqlite3Database, self).__init__(parent, config, instanceId)
        self._db = Sqlite3KeyValueStore(name, self.schemaVersion)
        self.ident = name + "Jobs"

    @property
    def db(self):
        return self._db

    @property
    def conn(self):
        return self._db.conn

    @conn.setter
    def conn(self, conn):
        self._db.conn = conn

    @property
    def dirty(self):
        return self._db.dirty

    def lock(self):
        self._db.lock()

    def unlock(self):
        self._db.unlock()

    def __getattr__(self, attr):
        return getattr(self._db, attr)


def connectDb(filename):
    conn = sqlite3.connect(filename)
    conn.isolation_level = 'EXCLUSIVE'
    return conn


class Sqlite3Jobs(JobsBase):
    def __init__(self, config, plugins):
        super(Sqlite3Jobs, self).__init__(config, plugins)
        self._filename = resolveDbFile(config, 'jobsDb.sqlite')
        self._lock.lock()
        conn = connectDb(self._filename)
        self.active = Sqlite3Database(self, config, self._instanceId, 'active')
        self.active.setup(conn)
        self.inactive = Sqlite3Database(
            self, config, self._instanceId, 'inactive')
        self.inactive.setup(conn)
        self._lock.unlock()

    def isLocked(self):
        return self._lock.isLocked()

    def lock(self):
        super(Sqlite3Jobs, self).lock()
        self._lock.lock()
        conn = connectDb(self._filename)
        self.active.conn = conn
        self.inactive.conn = conn
        self.active.lock()
        self.inactive.lock()
        conn.execute("begin")

    def unlock(self):
        super(Sqlite3Jobs, self).unlock()
        conn = self.active.conn
        if self.active.dirty or self.inactive.dirty:
            conn.commit()
        self.active.unlock()
        self.inactive.unlock()
        self.active.conn = None
        self.inactive.conn = None
        conn.close()
        self._lock.unlock()

import anydbm
import errno
import os
import shutil
import time

from . import DatabaseBase


class DbmDatabase(DatabaseBase):
    schemaVersion = "4"

    def __init__(self, parent, config, dbFile, instanceId, cached=False):
        # pylint: disable=too-many-arguments
        super(DbmDatabase, self).__init__(parent, config, dbFile, instanceId,
                                          cached=cached)

    def _openDb(self):
        if self._dbCache:
            return self._dbCache
        mode = 'r' if self._cached else 'c'
        db = anydbm.open(self.dbFile, mode)
        if (self.SV not in db or
                db[self.SV] != self.schemaVersion):
            db.close()
            if os.path.exists(self.dbFile):
                backup = self.dbFile + '.' + self._instanceId
                shutil.copy(self.dbFile, backup)
            db = anydbm.open(self.dbFile, 'n')
            db[self.SV] = self.schemaVersion
            db[self.LASTKEY] = ""
            db[self.LASTJOB] = ""
            db[self.ITEMCOUNT] = "0"
            db[self.CHECKPOINT] = ""
            db.close()
            db = anydbm.open(self.dbFile, mode)
        if self._cached:
            self._dbCache = db
        return db

    @property
    def db(self):
        for _ in range(5):
            try:
                return self._openDb()
            except anydbm.error as error:  # pylint: disable=catching-non-exception
                errNum = error.args[0]
                if errNum != errno.EAGAIN:
                    raise
                time.sleep(0.25)

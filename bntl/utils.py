
import os
import urllib
import re
from datetime import datetime, timezone

import aiofiles, aioconsole

from bntl.settings import settings


class MissingFieldException(Exception):
    pass


class YearFormatException(Exception):
    pass


def fix_year(doc):
    """
    Utility function dealing with different input formats for the year field.
    We validate the year, and add a end_year field to unify range search queries.
    """
    try:
        doc['end_year'] = int(doc['year']) + 1 # year is uninclusive
        return doc
    except Exception:
        # undefined years (eg. 197X), go for average value
        if 'X' in doc['year']:
            doc['year'] = doc['year'].replace('X', '5')
            return fix_year(doc)
        # range years (eg. 1987-2024, 1987-, ...)
        if '-' in doc['year']:
            m = re.match(r"([0-9]{4})-([0-9]{4})?", doc['year'])
            if not m: # error, skip the record
                raise YearFormatException({"input": doc['year']})
            start, end = m.groups()
            doc['year'] = start
            doc['end_year'] = end or int(start) + 1 # use starting date if end year is missing

    return doc


def identity(item): return item


def is_atlas(uri):
    """
    Check if the current URI corresponds to a Cloud Atlas database
    """
    return urllib.parse.urlparse(uri).netloc.endswith("mongodb.net")


def get_log_filename(file_id):
    return os.path.join(settings.UPLOAD_LOG_DIR, file_id + '.log')


class AsyncLogger:
    def __init__(self, log_file: str = None):
        self.log_file = log_file
        self.file = None

    async def __aenter__(self):
        if self.log_file:
            self.file = await aiofiles.open(self.log_file, mode='a')
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        if self.file:
            await self.file.close()

    async def log(self, message: str):
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] {message}\n"

        if self.file:
            await self.file.write(log_entry)
            await self.file.flush()
        else:
            await aioconsole.aprint(log_entry, end='')



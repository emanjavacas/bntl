
import os
import urllib
from datetime import datetime, timezone
import asyncio

import aiofiles, aioconsole

from bntl.settings import settings


def identity(item): return item


def is_atlas(uri):
    """
    Check if the current URI corresponds to a Cloud Atlas database
    """
    return urllib.parse.urlparse(uri).netloc.endswith("mongodb.net")


def get_log_filename(file_id):
    return os.path.join(settings.UPLOAD_LOG_DIR, file_id + '.log')


async def maybe_await(value):
    if asyncio.iscoroutine(value):
        return await value
    return value


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

    async def info(self, message: str):
        await self.log(message)

    async def debug(self, message: str):
        await self.log(message)



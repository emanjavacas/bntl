
import os
from collections import defaultdict
from datetime import datetime, timezone
import asyncio

import aiofiles, aioconsole

from bntl.settings import settings


def identity(item): return item


def default_to_regular(d):
    if isinstance(d, (defaultdict, dict)):
        d = {k: default_to_regular(v) for k, v in d.items()}
    return d


def get_log_filename(file_id):
    return os.path.join(settings.UPLOAD_LOG_DIR, file_id + '.log')


async def maybe_await(value):
    if asyncio.iscoroutine(value):
        return await value
    return value


class AsyncLogger:
    def __init__(self, log_file: str = None, force_print=True):
        self.log_file = log_file
        self.file = None
        self.force_print = force_print

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
        if self.force_print:
            await aioconsole.aprint(log_entry, end='')

    async def info(self, message: str):
        await self.log(message)

    async def debug(self, message: str):
        await self.log(message)


async def ris2xml(ris_data):
    proc = await asyncio.create_subprocess_exec(
        "ris2xml",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)

    xmlout, stderr = await proc.communicate(input=ris_data.encode())
    if proc.returncode == 0:
        return xmlout.decode()
    else:
        raise Exception(f"Process failed with exit code {proc.returncode}")


async def xml2bib(xml_data):
    proc = await asyncio.create_subprocess_exec(
        "xml2bib",
        "--no-bom", "-w",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)

    xmlout, stderr = await proc.communicate(input=xml_data.encode())
    if proc.returncode == 0:
        return xmlout.decode()
    else:
        raise Exception(f"Process failed with exit code {proc.returncode}")


async def ris2bib(ris_data):
    xml_data = await ris2xml(ris_data)
    return await xml2bib(xml_data)

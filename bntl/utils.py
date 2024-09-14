
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import List, Union
import asyncio

import aiofiles
import aioconsole

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


def maybe_list(inp: Union[List[str], str]):
    if isinstance(inp, list):
        if len(inp) == 1:
            return inp[0]
        *firsts, last = inp
        return ', '.join(firsts) + " & " + last
    return inp


RIS2DOC_SCREENNAMES = {
    "TY": "Publicatietype",
    "PY": "Publicatiejaar",
    "TI": "Titel",
    "T2": "Boektitel",
    "AB": "Extra informatie",
    "UR": "URL (link naar open acces)",
    "AU": "Auteur(s)",
    "A1": "Auteur(s)",
    "A2": "Redacteur(s)",
    "KW": "Trefwoord(en)",
    "SP": "Startpagina",
    "EP": "Eindpagina",
    "JO": "Tijdschrift",
    "VL": "Volume",
    "IS": "Nummer",
    "RN": "Recensie/Reactie",
    "SN": "ISBN-nummer",
    "CY": "Plaats van uitgave",
    "PB": "Uitgeverij",
    "N2": "Oude notatie",
    "C3": "Titelbeschrijving boek",
    "C4": "Gerelateerde artikels"
}
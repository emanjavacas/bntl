
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import List, Union
import asyncio

from rispy.config import TAG_KEY_MAPPING
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


def replace_ris(repr):
    for key, value in TAG_KEY_MAPPING.items():
        repr = repr.replace(key, value)
    return repr


def maybe_list(inp: Union[List[str], str]):
    if isinstance(inp, list):
        if len(inp) == 1:
            return inp[0]
        *firsts, last = inp
        return ', '.join(firsts) + " & " + last
    return inp


class DOC_REPR:
    JOUR = "[AU]. [TI]. In: [JO]: [VL] ([PY]) [IS], [SP]-[EP]."
    BOOK = "[AU]. [TI]. [CY]: [PB], [PY]. [EP] p."
    BOOK_2EDS = "[A2] (red.). [TI]. [CY]: [PB], [PY]. [EP] p."
    CHAP = "[A1]. [TI]. In: [A2] (red.). [T2]. [CY]: [PB], [PY], p. [SP]-[EP]."
    EJOUR = "[AU]. [TI]. Op: [JO]: [VL]."
    WEB = "[AU]. [TI]. [PY]."
    JFULL = "[TI]. Speciaal nummer van: [JO]: [VL] ([PY]) [IS], [SP]-[EP]."
    ADVS = "[AU]. [TI]. [CY]: [PB], [PY]."

    @staticmethod
    def get_repr_type(doc):
        if doc['type_of_reference'] == "JOUR":
            return DOC_REPR.JOUR
        elif doc['type_of_reference'] == "BOOK":
            if doc.get('secondary_authors') is not None:
                # ignore authors
                return DOC_REPR.BOOK_2EDS
            return DOC_REPR.BOOK
        elif doc['type_of_reference'] == "CHAP":
            return DOC_REPR.CHAP
        elif doc['type_of_reference'] == "JFULL":
            return DOC_REPR.JFULL
        elif doc['type_of_reference'] == "WEB":
            return DOC_REPR.WEB
        elif doc['type_of_reference'] == "ADVS":
            return DOC_REPR.ADVS
        elif doc['type_of_reference'] == 'EJOUR':
            return DOC_REPR.EJOUR
        else:
            raise ValueError("Unknown publication type: {}".format(doc['type_of_reference']))

    @staticmethod
    def render_doc(doc):
        repr_str = DOC_REPR.get_repr_type(doc)
        repr_str = replace_ris(repr_str.replace("[", "{").replace("]", "}"))
        # unwrap lists
        kwargs = {k: maybe_list(v) for k, v in doc.items()}
        # drop None items
        kwargs = {k: v for k, v in kwargs.items() if v}
        # handle missing keys
        kwargs = defaultdict(lambda: "N/A", kwargs)
        return repr_str.format_map(kwargs)


import json
import time
import logging
from typing import List

import aiohttp
import asyncio

from vectorizer.models import Status
from vectorizer.settings import settings
from vectorizer.utils import maybe_await


logger = logging.getLogger(__name__)


async def post_task(task_id: str, texts: List[str]):
    async with aiohttp.ClientSession() as session:
        async with session.post(
            'http://0.0.0.0:{}/vectorize?task_id={}'.format(settings.PORT, task_id), json=texts) as resp:
                return await resp.json()


async def get_task_status(task_id: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(
            'http://0.0.0.0:{}/check-status/{}'.format(settings.PORT, task_id)) as resp:
            return await resp.json()


async def get_vectors(task_id: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(
            'http://0.0.0.0:{}/get-vectors/{}'.format(settings.PORT, task_id)) as resp:
            # vectors = []
            output = b""
            async for line in resp.content.iter_chunked(100 * 1024):
                output += line
            return json.loads(output.decode("utf-8"))
        

def get_retry_time(n_docs):
    if n_docs > 50_000:
        return 120
    elif n_docs > 10_000:
        return 40
    elif n_docs > 1_000:
        return 20
    return 10


async def send_vectorizer_task_and_poll(task_id, texts, retry_time=None, timeout=3600 * 1, logger=logger):
    retry_time = retry_time or get_retry_time(len(texts))
    resp = await post_task(task_id, texts)

    # handle 404's, 500's, etc...
    if "status_code" in resp:
        await maybe_await(logger.info(str(resp)))
        return

    start = time.time()
    while resp["current_status"]["status"] != Status.DONE:
        # exit if timeout
        if (time.time() - start) > timeout:
            await maybe_await(logger.info("Request timed out, check again later"))
            break
        # check if error
        if resp["current_status"]["status"] in (Status.UNKNOWNERROR, Status.RUNTIMEERROR, Status.OUTOFATTEMPTS):
            await maybe_await(logger.info("Got error: [{}], exiting...".format(resp["current_status"]["status"])))
            break
        else:
            # sleep and retry
            await maybe_await(logger.info("Task in status: {}".format(resp["current_status"]["status"])))
            await maybe_await(logger.info("Sleeping for {} seconds...".format(retry_time)))
            await asyncio.sleep(retry_time)
        resp = await get_task_status(task_id)
    else: # done, retrieve vectors
        await maybe_await(
            logger.info("Vectorization done in {} seconds".format(round(time.time() - start, 2))))
        return await get_vectors(task_id)

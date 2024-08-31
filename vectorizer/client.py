
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
            return await resp.json()


async def send_vectorizer_task_and_poll(task_id, texts, retry_time=15, timeout=3600 * 1, logger=logger):
    resp = await post_task(task_id, texts)

    # handle 404's, 500's, etc...
    if "status_code" in resp:
        await maybe_await(logger.info(str(resp)))
        return

    start = time.time()
    while resp["current_status"]["status"] != Status.DONE:
        # exist if timeout
        if (time.time() - start) > timeout:
            await maybe_await(logger.info("Request timed out, check again later"))
            break
        # check error
        if resp["current_status"]["status"] in (Status.UNKNOWNERROR, Status.RUNTIMEERROR):
            await maybe_await(logger.info("Exiting"))
            break
        else:
            # sleep and retry
            await maybe_await(logger.info("Task in status: {}".format(resp["current_status"]["status"])))
            await maybe_await(logger.info("sleeping for {} seconds".format(retry_time)))
            await asyncio.sleep(retry_time)
        resp = await get_task_status(task_id)
    else: # done, retrieve vectors
        await maybe_await(
            logger.info("Vectorization done in {} seconds.".format(round(time.time() - start, 2))))
        return await get_vectors(task_id)

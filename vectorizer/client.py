
import time
import logging
from typing import List, Union

import aiohttp
import asyncio

import pymongo
from motor.motor_asyncio import AsyncIOMotorCollection

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
        

def get_retry_time(n_docs):
    if n_docs > 50_000:
        return 120
    elif n_docs > 10_000:
        return 40
    elif n_docs > 1_000:
        return 20
    return 10


async def vectorize(task_id: str, texts: List[str], vectors_coll: AsyncIOMotorCollection, 
                    retry_time: Union[None, float]=None, timeout: float=3600 * 2,
                    logger=logger) -> Union[List[float] | None]:
    """
    Start vectorize task and monitor the status until done, error or timeout
    """
    retry_time = retry_time or get_retry_time(len(texts))
    resp = await post_task(task_id, texts)

    # handle 500's, etc...
    if "status_code" in resp:
        await maybe_await(logger.info(str(resp)))
        return 

    start = time.time()
    while resp["current_status"]["status"] != Status.DONE:
        # exit if timeout
        if (time.time() - start) > timeout:
            await maybe_await(logger.info("Client timeout when vectorizing..."))
            return
        # check if error
        if resp["current_status"]["status"] in (Status.RETRYING, Status.VECTORIZING):
            await maybe_await(logger.info("Task in status: {}".format(resp["current_status"]["status"])))
            await maybe_await(logger.info("Sleeping for {} seconds...".format(retry_time)))
            await asyncio.sleep(retry_time)
            resp = await get_task_status(task_id)
        else:
            await maybe_await(logger.info("Error while vectorizing..."))
            await maybe_await(logger.info(str(resp["current_status"]["status"])))
            return
    else: # done
        await maybe_await(logger.info("Vectorization done in {} secs".format(round(time.time() - start, 2))))
        vectors = await vectors_coll.find(
            {"task_id": task_id}
        ).sort("vector_id", pymongo.DESCENDING).to_list(length=None)
        return [item["vector"] for item in vectors]

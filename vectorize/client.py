
import time
import logging
from typing import List, Union

import aiohttp
import asyncio

import pymongo
from motor.motor_asyncio import AsyncIOMotorCollection

from bntl.settings import settings as bntl_settings
from vectorize.models import Status
from vectorize.utils import maybe_await


logger = logging.getLogger(__name__)


async def post_task(task_id: str, texts: List[str], doc_ids: List[str]):
    async with aiohttp.ClientSession() as session:
        url = 'http://{}:{}/vectorize'.format(
            bntl_settings.VECTORIZER_HOST,
            bntl_settings.VECTORIZER_PORT)
        data = {"task_id": task_id, "texts": texts, "doc_ids": doc_ids}
        async with session.post(url, json=data) as resp:
            return await resp.json()


async def get_task_status(task_id: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(
            'http://{}:{}/check-status/{}'.format(
                bntl_settings.VECTORIZER_HOST,
                bntl_settings.VECTORIZER_PORT, 
                task_id)) as resp:
            return await resp.json()


def get_retry_time(n_docs):
    if n_docs > 50_000:
        return 120
    elif n_docs > 10_000:
        return 40
    elif n_docs > 1_000:
        return 20
    return 10


class VectorizationException(Exception):
    def __init__(self, message, error_data=None):
        super().__init__(message)
        self.error_data = error_data


async def vectorize(vectors_coll: AsyncIOMotorCollection, 
                    task_id: str, 
                    texts: List[str], 
                    doc_ids: Union[None, List[str]]=None, 
                    retry_time: Union[None, float]=None,
                    timeout: float=3600 * 2,
                    logger=logger) -> Union[List[float] | None]:
    """
    Start vectorize task and monitor the status until done, error or timeout
    """
    retry_time = retry_time or get_retry_time(len(texts))
    resp = await post_task(task_id, texts, doc_ids or list(map(str, range(len(texts)))))

    # handle 500's, etc...
    if "status_code" in resp:
        await maybe_await(logger.info(str(resp)))
        return VectorizationException(str(resp))

    start = time.time()
    while resp["current_status"]["status"] != Status.DONE:
        # exit if timeout
        if (time.time() - start) > timeout:
            raise VectorizationException("Client timeout when vectorizing...")
        # check if error
        if resp["current_status"]["status"] in (Status.RETRYING, Status.VECTORIZING):
            await maybe_await(logger.info("Task in status: {}".format(resp["current_status"]["status"])))
            await maybe_await(logger.info("Sleeping for {} seconds...".format(retry_time)))
            await asyncio.sleep(retry_time)
            resp = await get_task_status(task_id)
        else:
            raise VectorizationException("Error while vectorizing", error_data=resp["current_status"]["status"])
    else: # done
        await maybe_await(logger.info("Vectorization done in {} secs".format(round(time.time() - start, 2))))
        vectors = await vectors_coll.find(
            {"task_id": task_id}
        ).sort("vector_id", pymongo.DESCENDING).to_list(length=None)
        return [item["vector"] for item in vectors]

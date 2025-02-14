
import logging
from typing import List
from contextlib import asynccontextmanager

import asyncio
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.concurrency import run_in_threadpool
import pymongo

import torch

from vectorize.model_manager import ModelManagerFE, ModelManagerStella
from vectorize.settings import setup_logger, settings
from vectorize.models import Status, TaskModel, VectorizeParams
from vectorize.db import DBClient


setup_logger()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.model_manager = ModelManagerStella("dunzhang/stella_en_1.5B_v5")
    # app.state.model_manager = ModelManagerFE('BAAI/bge-m3')
    app.state.db_client = await DBClient.create()
    yield
    app.state.model_manager.close()
    app.state.db_client.close()


app = FastAPI(title="Vectorizer Backend", lifespan=lifespan)


async def vectorize_task(task_id, texts, doc_ids):
    attempts = 0

    while attempts < settings.MAX_RETRIES:
        if torch.cuda.is_available():
            # Attempt to move the model to GPU and run the task
            try:
                app.state.model_manager.load_model()
                app.state.model_manager.move_model_to_gpu()
                # Cache
                if text2vector := await app.state.db_client.retrieve_cache(texts):
                    logger.info("Got {}/{} vectors from cache".format(len(text2vector), len(texts)))
                    if input_texts := [text for text in texts if text not in text2vector]:
                        logger.info("Vectorizing {} remaining docs".format(len(input_texts)))
                        vectors = await run_in_threadpool(
                            app.state.model_manager.get_model().encode, input_texts, settings.BATCH_SIZE)
                        # merge vectors
                        text2vector.update(zip(input_texts, vectors.tolist()))
                    vectors = [text2vector[text] for text in texts]
                else:
                    logger.info("Vectorizing {} docs".format(len(texts)))
                    vectors = await run_in_threadpool(
                        app.state.model_manager.get_model().encode, texts, settings.BATCH_SIZE)
                    vectors = vectors.tolist()
                app.state.model_manager.move_model_to_cpu()    
                # store vectors
                logger.info("Storing vectors...")
                await app.state.db_client.store_vectors(task_id, vectors, doc_ids)
                # Update the task status to done
                await app.state.db_client.update_task_status(task_id, Status.DONE)
                break
            except Exception as e:
                if "CUDA out of memory" in str(e):
                    await app.state.db_client.update_task_status(
                        task_id, Status.RETRYING, attempts=attempts, message="GPU OOM", e=str(e))
                    await asyncio.sleep(settings.RETRY_DELAY)
                    attempts += 1
                    continue
                else:
                    await app.state.db_client.update_task_status(
                        task_id, Status.RUNTIMEERROR, attempts=attempts, e=str(e))
                    break
        else:
            await app.state.db_client.update_task_status(
                task_id, Status.RETRYING, attempts=attempts, message="GPU not available")
            await asyncio.sleep(settings.RETRY_DELAY)
            attempts += 1

    if attempts >= settings.MAX_RETRIES:
        await app.state.db_client.update_task_status(task_id, Status.TIMEOUT)


@app.post("/vectorize")
async def vectorize(params: VectorizeParams, background_tasks: BackgroundTasks):
    task_id, texts, doc_ids = params.task_id, params.texts, params.doc_ids
    try:
        task = await app.state.db_client.create_task(task_id, texts, doc_ids)
        background_tasks.add_task(vectorize_task, task_id, texts, doc_ids)
        return task
    except pymongo.errors.DuplicateKeyError:
        raise HTTPException(status_code=500, detail="Document already vectorized")
    except Exception as e:
        logger.info("Error while vectorizing")
        logger.info(str(e))
        raise HTTPException(status_code=500, detail="Unknown error while vectorizing: " + str(e))


@app.get("/check-status/{task_id}", response_model=TaskModel)
async def task_status(task_id: str):
    task = await app.state.db_client.get_task(task_id)
    if task:
        return task
    else:
        raise HTTPException(status_code=404, detail="Task not found")
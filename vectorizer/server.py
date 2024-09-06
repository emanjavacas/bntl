
import logging
from typing import List
from contextlib import asynccontextmanager

import asyncio
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.concurrency import run_in_threadpool
import pymongo

import torch

from vectorizer.model_manager import ModelManagerFE, ModelManagerStella
from vectorizer.settings import setup_logger, settings
from vectorizer.models import Status, TaskModel, VectorizeParams
from vectorizer.db import DBClient


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
                vectors = await run_in_threadpool(
                    app.state.model_manager.get_model().encode, texts, settings.BATCH_SIZE)
                vectors = vectors.tolist()
                app.state.model_manager.move_model_to_cpu()
                # Update the task status to done
                await app.state.db_client.store_vectors(task_id, vectors, doc_ids)
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
        raise HTTPException(status_code=500, detail="Unknown " + str(e))


@app.get("/check-status/{task_id}", response_model=TaskModel)
async def task_status(task_id: str):
    task = await app.state.db_client.get_task(task_id)
    if task:
        return task
    else:
        raise HTTPException(status_code=404, detail="Task not found")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    import uvicorn
    uvicorn.run("server:app",
                host='0.0.0.0',
                port=settings.PORT,
                workers=settings.WORKERS,
                reload=args.debug)


import uuid
import logging
from typing import List
from contextlib import asynccontextmanager

import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
import pymongo

import torch

from vectorizer.settings import setup_logger, settings
from vectorizer.models import Status, TaskModel
from vectorizer.model_manager import ModelManager
from vectorizer.db import DBClient

setup_logger()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.model_manager = ModelManager()
    app.state.db_client = await DBClient.create()
    yield
    app.state.model_manager.close()
    app.state.db_client.close()


app = FastAPI(title="Vectorizer Backend", lifespan=lifespan)


def encode(model, text, batch_size):
    return model.encode(text, batch_size=batch_size)


async def vectorize_task(task_id, texts):
    attempts = 0

    while attempts < settings.MAX_RETRIES:
        if torch.cuda.is_available():
            # Attempt to move the model to GPU and run the task
            try:
                app.state.model_manager.load_model()
                app.state.model_manager.move_model_to_gpu()
                vectors = await run_in_threadpool(
                    encode, app.state.model_manager.get_model(), texts, settings.BATCH_SIZE)
                vectors = vectors.tolist()
                app.state.model_manager.move_model_to_cpu()
                # Update the task status to done
                await app.state.db_client.update_task_status(task_id, Status.DONE, vectors=vectors)
                break
            except Exception as e:
                if "CUDA out of memory" in str(e):
                    logger.info(f"GPU out of memory, retrying task [{task_id}]...")
                    await app.state.db_client.update_task_status(
                        task_id, Status.RETRYING, attempts=attempts, message="GPU OOM")
                    await asyncio.sleep(settings.RETRY_DELAY)
                    attempts += 1
                    continue
                else:
                    await app.state.db_client.update_task_status(
                        task_id, Status.RUNTIMEERROR, attempts=attempts)
                    logger.info(f"Unknown error for task [{task_id}]")
                    logger.info(str(e))
                    break
        else:
            logger.info(f"GPU not available, retrying task {task_id}...")
            await app.state.db_client.update_task_status(
                task_id, Status.RETRYING, attempts=attempts, message="GPU not available")
            await asyncio.sleep(settings.RETRY_DELAY)
            attempts += 1

    if attempts >= settings.MAX_RETRIES:
        await app.state.db_client.update_task_status(task_id, Status.OUTOFATTEMPTS)


@app.post("/vectorize")
async def vectorize(task_id: str, texts: List[str]):
    try:
        task = await app.state.db_client.create_task(task_id, texts)
        await vectorize_task(task_id, texts)
        # background_tasks.add_task(vectorize_task, task_id, texts)
        return task
    except pymongo.errors.DuplicateKeyError:
        raise HTTPException(status_code=404, detail="Document already vectorized")
    except Exception as e:
        logger.info("Error while vectorizing")
        logger.info(str(e))
        raise HTTPException(status_code=500, detail="Couldn't vectorize: " + str(e))


@app.get("/check-status/{task_id}", response_model=TaskModel)
async def task_status(task_id: str):
    task = await app.state.db_client.get_task(task_id)
    if task:
        return task
    else:
        raise HTTPException(status_code=404, detail="Task not found")


@app.get("/get-vectors/{task_id}")
async def get_vectors(task_id: str):
    task = await app.state.db_client.get_task(task_id)
    if task and task["current_status"]["status"] == Status.DONE:
        vectors = await app.state.db_client.vectors_coll.find(
            {"task_id": task_id}
        ).sort("vector_id", pymongo.DESCENDING).to_list(length=None)
        return [vector["vector"] for vector in vectors]
    raise HTTPException(status_code=404, detail="Task not done")    


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

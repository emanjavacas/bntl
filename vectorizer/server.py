
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from contextlib import asynccontextmanager

import asyncio
import pymongo
import motor.motor_asyncio as motor
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, BackgroundTasks

import torch
from sentence_transformers import SentenceTransformer

from vectorizer.settings import setup_logger, settings

setup_logger()
logger = logging.getLogger(__name__)


class ModelManager:
    def __init__(self):
        self.model = None

    def load_model(self):
        if self.model is None:
            self.model = SentenceTransformer("dunzhang/stella_en_1.5B_v5", trust_remote_code=True)
            self.model = self.model.to(torch.device('cpu'))
            logger.info("Model loaded on CPU.")

    def move_model_to_gpu(self):
        if self.model.device != torch.device('cuda'):
            logger.info("Moving model to GPU...")
            self.model = self.model.to(torch.device('cuda'))
            logger.info("Model moved to GPU.")

    def move_model_to_cpu(self):
        if self.model.device != torch.device('cpu'):
            logger.info("Moving model back to CPU...")
            self.model = self.model.to(torch.device('cpu'))
            logger.info("Model moved back to CPU.")

    def get_model(self):
        if self.model is None:
            self.load_model()
        return self.model
    
    def close(self):
        if self.model:
            self.move_model_to_cpu()


class Status:
    DONE = 'Done!'
    RETRYING = 'Retrying...'
    VECTORIZING = 'Vectorizing...'
    UNKNOWNERROR = 'Unknown error'
    OUTOFATTEMPTS = 'Task ran out of attempts'


class StatusModel(BaseModel):
    status: str
    date_created: datetime
    status_info: Optional[Dict[Any, Any]]


class TaskModel(BaseModel):
    _id: Optional[str] = None
    task_id: str
    texts: List[str]
    date_created: datetime
    current_status: StatusModel
    history: Optional[List[StatusModel]] = []
    vectors: Optional[Any] = None


def create_new_status(status, **status_info) -> StatusModel:
    return StatusModel(status=status, date_created=datetime.now(timezone.utc), status_info=status_info)


class DBClient():
    def __init__(self) -> None:
        self.db_client = motor.AsyncIOMotorClient(settings.DB_URI)
        self.coll = self.db_client[settings.VECTORIZER_DB][settings.TASKS_COLL]

    @classmethod
    async def create(cls):
        self = cls()
        self.coll.create_index("task_id", unique=True)
        return self

    def close(self):
        self.db_client.close()

    async def create_task(self, task_id, texts) -> TaskModel:
        task = TaskModel(task_id=task_id,
                         texts=texts,
                         current_status=create_new_status(Status.VECTORIZING),
                         date_created=datetime.now(timezone.utc))
        await app.state.db_client.coll.insert_one(task.model_dump())
        logger.info(f"Created task [{task_id}]")
        return task.model_dump()
    
    async def get_task(self, task_id):
        doc = await app.state.db_client.coll.find_one({"task_id": task_id})
        doc.pop("_id")
        return doc

    async def update_task_status(self, task_id, status, vectors=None, **status_info):
        logger.info(f"Task [{task_id}] updated to status: {status}")
        if status_info:
            logger.info(str(status_info))
        old_status = (await self.get_task(task_id))["current_status"]
        update = {"$set": {"current_status": create_new_status(status, **status_info).model_dump()}}
        if vectors is not None:
            update["$set"]["vectors"] = vectors
        update["$push"] = {"history": old_status}
        return await self.coll.update_one(
            {"task_id": task_id}, update, upsert=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.model_manager = ModelManager()
    app.state.db_client = await DBClient.create()
    yield
    app.state.model_manager.close()
    app.state.db_client.close()


app = FastAPI(title="Vectorizer Backend", lifespan=lifespan)


async def vectorize_task(task_id, texts):
    attempts = 0

    while attempts < settings.MAX_RETRIES:

        if torch.cuda.is_available():
            # Attempt to move the model to GPU
            try:
                app.state.model_manager.load_model()
                app.state.model_manager.move_model_to_gpu()
            except RuntimeError as e:
                if "CUDA out of memory" in str(e):
                    logger.info(f"GPU out of memory, retrying task [{task_id}]...")
                    await app.state.db_client.update_task_status(
                        task_id, Status.RETRYING, attempts=attempts)
                    await asyncio.sleep(settings.RETRY_DELAY)
                    attempts += 1
                    continue
                else:
                    await app.state.db_client.update_task_status(
                        task_id, Status.UNKNOWNERROR, attempts=attempts)
                    logger.info(f"Unknown error for task [{task_id}]")
                    logger.info(str(e))
                    break

            # Generate the vector
            vectors = app.state.model_manager.get_model().encode(
                texts, batch_size=settings.BATCH_SIZE)
            vectors = vectors.tolist()
            app.state.model_manager.move_model_to_cpu()

            # Update the task status to 'completed'
            await app.state.db_client.update_task_status(task_id, Status.DONE, vectors)
            break

        else:
            logger.info(f"GPU not available, retrying task {task_id}...")
            await app.state.db_client.update_task_status(
                task_id, Status.RETRYING, attempts + 1)
            await asyncio.sleep(settings.RETRY_DELAY)
            attempts += 1

    if attempts >= settings.MAX_RETRIES:
        await app.state.db_client.update_task_status(task_id, Status.OUTOFATTEMPTS)


@app.post("/generate-vector")
async def generate_vector(task_id: str, texts: List[str], background_tasks: BackgroundTasks):
    try:
        task = await app.state.db_client.create_task(task_id, texts)
        background_tasks.add_task(vectorize_task, task_id, texts)
        return task
    except pymongo.errors.DuplicateKeyError:
        return HTTPException(status_code=404, detail="Document already vectorized")


@app.get("/task-status/{task_id}", response_model=TaskModel)
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

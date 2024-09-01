
import logging
from datetime import datetime, timezone

import motor.motor_asyncio as motor
from pymongo import UpdateOne

from vectorizer.models import StatusModel, TaskModel, VectorModel, Status
from vectorizer.settings import settings

logger = logging.getLogger(__name__)


def create_new_status(status, **status_info) -> StatusModel:
    return StatusModel(status=status, date_created=datetime.now(timezone.utc), status_info=status_info)


class DBClient():
    def __init__(self, ) -> None:
        self.db_client = motor.AsyncIOMotorClient(settings.DB_URI)
        self.tasks_coll = self.db_client[settings.VECTORIZER_DB][settings.TASKS_COLL]
        self.vectors_coll = self.db_client[settings.VECTORIZER_DB][settings.VECTORS_COLL]

    @classmethod
    async def create(cls):
        self = cls()
        await self.ensure_indices()
        return self

    async def ensure_indices(self):
        # ensure unique index
        logger.info("Creating DB indices")
        await self.tasks_coll.create_index("task_id", unique=True)
        await self.vectors_coll.create_index(["task_id", "vector_id"], unique=True)
    
    def close(self):
        self.db_client.close()

    async def create_task(self, task_id, texts) -> TaskModel:
        # create task
        task = TaskModel(task_id=task_id,
                         current_status=create_new_status(Status.VECTORIZING),
                         date_created=datetime.now(timezone.utc))
        await self.tasks_coll.insert_one(task.model_dump())
        # create vector entries
        await self.vectors_coll.insert_many(
            [VectorModel(task_id=task_id, vector_id=idx, text=text).model_dump()
             for idx, text in enumerate(texts)])
        # done
        logger.info(f"Created task [{task_id}]")
        return task.model_dump()
    
    async def get_task(self, task_id):
        doc = await self.tasks_coll.find_one({"task_id": task_id})
        doc.pop("_id")
        return doc

    async def update_task_status(self, task_id, status, vectors=None, **status_info):
        logger.info(f"Task [{task_id}] updated to status: {status}")
        logger.info("Status info: " + str(status_info))
        old_status = (await self.get_task(task_id))["current_status"]
        # update task status
        task_update = await self.tasks_coll.update_one(
            {"task_id": task_id}, 
            {"$set": {"current_status": create_new_status(status, **status_info).model_dump()},
             "$push": {"history": old_status}}, 
             upsert=True)
        # update vectors
        if vectors is not None:
            await self.vectors_coll.bulk_write(
                [UpdateOne({"task_id": task_id, "vector_id": idx},
                           {"$set": {"vector": vector}})
                 for idx, vector in enumerate(vectors)])
        return task_update
    
    async def _clear_up(self):
        await self.vectors_coll.drop()
        await self.tasks_coll.drop()
        # ensure we recreate the indices
        await self.ensure_indices()
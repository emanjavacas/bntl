
import logging
from datetime import datetime, timezone

from bntl import utils
from bntl.models import StatusModel
from vectorizer.client import vectorize, VectorizationException


logger = logging.getLogger(__name__)


class Status:
    VECTORIZING = 'Vectorizing...'
    VECTORIZINGERROR = 'Error while vectorizing'
    VECTORINDEXINGERROR = 'Vector indexing error'
    UNKNOWNERROR = "Unknown error"
    DONE = 'Done'

    @classmethod
    def __get_classes__(cls):
        return {key: getattr(cls, key) for key in vars(cls).keys() if not key.startswith('__')}
    
    @classmethod
    def is_done(cls, status):
        return status in (cls.VECTORINDEXINGERROR, cls.VECTORIZINGERROR, cls.UNKNOWNERROR, cls.DONE)


async def update_status(db_client, task_id, status, **kwargs):
    """
    Utility function to keep track of the task status
    """
    logger.info(f"Received status [{status}] for task {task_id}")
    await db_client.update_vectorization_status(
        task_id, StatusModel(status=status,
                             date_updated=datetime.now(timezone.utc),
                             **kwargs))


async def vectorize_task(db_client, vector_client, task_id):
    vectors = None
    async with utils.AsyncLogger(utils.get_vectorization_log_filename(task_id)) as a_logger:
        try:
            docs = await db_client.find()
            texts, doc_ids = [], []
            for doc in docs:
                if text := utils.convert_to_text(doc["document"]):
                    texts.append(text)
                    doc_ids.append(doc["document"]["id"])
            if len(texts) == 0:
                await a_logger.info("No documents found in database")
                await update_status(db_client, task_id, Status.DONE)
            else:
                await a_logger.info("Starting vectorization task: {}".format(task_id))
                await a_logger.info("Vectorizing {} documents...".format(len(docs)))
                vectors = await vectorize(
                    db_client.vectors_coll, task_id, texts, doc_ids, logger=a_logger)
        except VectorizationException as e:
            await a_logger.info("Exception while vectorizing: [{}]".format(str(e)))
            await update_status(db_client, task_id, Status.VECTORIZINGERROR, detail=str(e))
        except Exception as e:
            await a_logger.info("Exception while vectorizing: [{}]".format(str(e)))
            await update_status(db_client, task_id, Status.VECTORIZINGERROR, detail=str(e))
        finally:
            if vectors:
                try:
                    await a_logger.info("Clearing up vector database")
                    await vector_client._clear_up()
                    await a_logger.info("Indexing...")
                    await vector_client.insert(vectors, doc_ids)
                    await a_logger.info("Done indexing")
                    await update_status(
                        db_client, task_id,
                        Status.DONE, detail=str("Indexed {} documents".format(len(vectors))))
                except Exception as e:
                    await update_status(db_client, task_id, Status.VECTORINDEXINGERROR, detail=str(e))
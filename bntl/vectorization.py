
import logging
from datetime import datetime, timezone

import openai

from bntl import utils
from bntl.models import StatusModel
from bntl.settings import settings


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


async def vectorize(texts, a_logger=logger):
    client = openai.AsyncClient(
        api_key=settings.VECTORIZER_API_KEY, 
        base_url=f"{settings.VECTORIZER_HOST}:{settings.VECTORIZER_PORT}/v1")

    vectors = []
    for i in range(0, len(texts), settings.VECTORIZER_BATCH_SIZE):
        await utils.maybe_await(
            a_logger.info("- vectorizing batch: {start}-{end}".format(
                start=i,
                end=min(len(texts), i+ settings.VECTORIZER_BATCH_SIZE))))
        batch = texts[i:i + settings.VECTORIZER_BATCH_SIZE]
        embs = await client.embeddings.create(input=batch, model=settings.VECTORIZER_MODEL)
        vectors.extend([item.embedding for item in embs.data])
    return vectors


async def get_texts_from_db(db_client):
    docs = await db_client.find()
    texts, doc_ids = [], []
    for doc in docs:
        if text := utils.convert_to_text(doc["document"]):
            texts.append(text)
            doc_ids.append(doc["document"]["id"])
    return texts, doc_ids


async def vectorize_task(db_client, vector_client, task_id):
    vectors = None
    async with utils.AsyncLogger(utils.get_vectorization_log_filename(task_id)) as a_logger:
        try:
            texts, doc_ids = await get_texts_from_db(db_client)
            # no texts, return
            if len(texts) == 0:
                await a_logger.info("No documents found in database")
                await update_status(db_client, task_id, Status.DONE)
                return

            await a_logger.info("Starting vectorization task: {}".format(task_id))
            # check cache
            if vector_cache := await db_client.get_vector_cache(texts):
                await a_logger.info("Got {}/{} vectors from cache".format(len(vector_cache), len(texts)))
                if remaining_texts := [text for text in texts if text not in vector_cache]:
                    await a_logger.info("Vectorizing {} remaining docs".format(len(remaining_texts)))
                    vectors = await vectorize(remaining_texts)
                    await a_logger.info("Caching vectors", a_logger=a_logger)
                    await db_client.store_vectors(task_id, remaining_texts, vectors)
                    vector_cache.update(zip(remaining_texts, vectors))
                # sort to original order
                vectors = [vector_cache[text] for text in texts]
            # no vectors found in cache
            else:
                await a_logger.info("Vectorizing {} docs".format(len(texts)))
                vectors = await vectorize(texts, a_logger=a_logger)
                await a_logger.info("Caching vectors")
                await db_client.store_vectors(task_id, texts, vectors)
            await a_logger.info("Got {} vectors".format(len(vectors)))
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
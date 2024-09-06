
import bson
import uuid
import asyncio
import rispy
import aiofiles

from bntl import utils
from bntl.db import DBClient
from bntl.vector import VectorClient
from bntl.upload import convert_to_text
from vectorizer import client


async def main(path):
    vector_client = VectorClient()
    db_client = await DBClient.create()

    async with utils.AsyncLogger() as logger:
        # clean db
        await logger.info("Cleaning up MongoDB collections")
        await db_client._clear_up()
        await logger.info("Cleaning up QDrant collections")
        await vector_client._clear_up()

        # read data from file
        async with aiofiles.open(path, 'r') as f:
            await logger.info("Loading data from file")
            docs = rispy.loads(await f.read())

        # insert documents
        await logger.info("Inserting {} docs from file: {}".format(len(docs), path))
        async def callback(progress):
            await logger.info("Inserted {} from {} documents.".format(progress, len(docs)))
        done = await db_client.insert_documents(docs, logger=logger, progress_callback=callback)
        
        # vectorize
        await logger.info("Vectorizing...")
        task_id = str(uuid.uuid4())
        docs = await db_client.find({"_id": {"$in": [bson.objectid.ObjectId(id) for id in done]}})
        texts = [convert_to_text(doc, ignore_keywords=True) for doc in docs]
        doc_ids = [str(doc["_id"]) for doc in docs]
        vectors = await client.vectorize(db_client.vectors_coll, task_id, texts, doc_ids, logger=logger)

        # insert to qdrant
        if vectors:
            await logger.info("Ingesting vectors into vector database")
            await vector_client.insert(vectors, [str(doc["_id"]) for doc in docs])
        else:
            await logger.info("Vectorization task failed, check logs to see what happened.")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--ris-file', required=True, help="Path to ris file with data to be indexed.")
    args = parser.parse_args()

    asyncio.run(main(args.ris_file))

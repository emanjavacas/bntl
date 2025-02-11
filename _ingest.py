
from copy import deepcopy
import uuid
import asyncio
import rispy
import aiofiles

from bntl import utils
from bntl.rdf import parse_rdf
from bntl.db import DBClient
from bntl.vector import VectorClient
from bntl.upload import convert_to_text
from vectorize import client


async def main(paths):
    vector_client = VectorClient()
    db_client = await DBClient.create()

    async with utils.AsyncLogger() as logger:
        # clean db
        await logger.info("Cleaning up MongoDB collections")
        await db_client._clear_up()
        await logger.info("Cleaning up QDrant collections")
        await vector_client._clear_up()

        for path in paths:
            # read data from file
            async with aiofiles.open(path, 'r') as f:
                await logger.info("Loading data from file: {}".format(path))
                ris_data = parse_rdf(await f.read())
                docs = rispy.loads(ris_data, mapping=utils.RISPY_MAPPING)

            # insert documents
            await logger.info("Inserting {} docs from file: {}".format(len(docs), path))
            async def callback(progress):
                await logger.info("Processed {}/{} documents.".format(progress, len(docs)))
            done = await db_client.insert_documents(docs, logger=logger, progress_callback=callback)
            
            # vectorize
            await logger.info("Vectorizing...")
            docs = await db_client.find({"document.id": {"$in": done}})
            texts, doc_ids = [], []
            for doc in docs:
                if text := convert_to_text(doc["document"]):
                    texts.append(text)
                    doc_ids.append(doc["document"]["id"])
            task_id = str(uuid.uuid4())
            vectors = await client.vectorize(db_client.vectors_coll, task_id, texts, doc_ids, logger=logger)

            # insert to qdrant
            if vectors:
                await logger.info("Ingesting vectors into vector database")
                await vector_client.insert(vectors, doc_ids)
            else:
                await logger.info("Vectorization task failed, check logs to see what happened.")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--rdf-files', required=True, nargs="+", help="Path to rdf file with data to be indexed.")
    args = parser.parse_args()
    asyncio.run(main(args.rdf_files))

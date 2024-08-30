
import bson
import logging
import collections
from datetime import datetime, timezone
from typing import Dict

import bson.objectid
import pymongo
import asyncio
import aiofiles
from pydantic import ValidationError
import rispy

from bntl import utils
from bntl.models import EntryModel, StatusModel


logger = logging.getLogger(__name__)


class Status:
    UPLOADING = 'Uploading...'
    INDEXING = 'Indexing...'
    VECTORIZING = 'Vectorizing...'
    UNKNOWNERROR = 'Unknown error'
    UNKNOWNFORMAT = 'Unknown input format'
    EMPTYFILE = 'Empty input file'
    DONE = 'Done'

    @classmethod
    def __get_classes__(cls):
        return {key: getattr(cls, key) for key in vars(cls).keys() if not key.startswith('__')}


def get_doc_text(doc):
    title = doc["title"] # seems mandatory
    if doc.get("secondary_title"):
        title += "; " + doc["secondary_title"]
    keywords = None
    if doc.get("keywords"):
        keywords = "; ".join(doc["keywords"])

    return {"title": title, "keywords": keywords}


def convert_to_text(doc, ignore_keywords=False):
    output = doc["title"]
    if doc["keywords"] and not ignore_keywords:
        output += "; " + doc["keywords"]
    return output


def run_validation(doc):
    # this needs to happen before model validation, since we are also doing stuff on the year
    if "year" not in doc:
        raise utils.MissingFieldException({"field": "year"})
    doc = utils.fix_year(doc)
    doc = EntryModel.model_validate(doc).model_dump()
    doc["date_added"] = datetime.now(timezone.utc)
    return doc


async def insert_documents(db_client, documents, logger, 
                           progress_callback=None, run_every=1_000):
    """
    General document ingestion logic
    """
    done = []
    for doc_idx, doc in enumerate(documents):
        try:
            doc = run_validation(doc)
            doc_id = (await db_client.bntl_coll.insert_one(doc)).inserted_id
            done.append(str(doc_id))
        except utils.YearFormatException as e:
            await logger.log("Dropping document #{} due to wrong year format".format(doc_idx))
            await logger.log(str(e))
        except ValidationError as e:
            await logger.log("Dropping document #{} due to wrong data format".format(doc_idx))
            await logger.log(str(e))
        except utils.MissingFieldException as e:
            await logger.log("Dropping document #{} due to missing field".format(doc_idx))
            await logger.log(str(e))

        except pymongo.errors.BulkWriteError as e:
            for error in e.details['writeErrors']:
                await logger.log("Write error [{}] for document #{}: '{}'".format(
                    error['code'], doc_idx, error['errmsg']))
        
        # progress
        if progress_callback is not None and doc_idx % run_every == 0:
            value = progress_callback(doc_idx)
            if asyncio.iscoroutine(value):
                await value

    return done


class FileUploadManager:
    def __init__(self, db_client, vector_client) -> None:
        self.file_chunks: Dict[str, Dict[int, bytes]] = collections.defaultdict(dict)
        self.db_client = db_client
        self.vector_client = vector_client

    def add_chunk(self, file_id: str, chunk_number: int, chunk_data: bytes):
        self.file_chunks[file_id][chunk_number] = chunk_data

    async def update_status(self, file_id, status, **kwargs):
        """
        Utility function
        """
        logger.info(f"Received status [{status}] for file {file_id}")
        await self.db_client.update_upload_status(
            file_id, StatusModel(status=status, 
                                 date_updated=datetime.now(timezone.utc),
                                 **kwargs))
        
    async def insert_documents(self, documents, file_id):
        async def callback(progress):
            await self.update_status(file_id, Status.INDEXING, process=progress/len(documents))
        async with utils.AsyncLogger(utils.get_log_filename(file_id)) as logger:
            return await insert_documents(self.db_client, documents, logger, progress_callback=callback)

    async def process_file(self, file_id: str):
        file_data = b''.join([self.file_chunks[file_id][i] for i in range(len(self.file_chunks[file_id]))])
        documents = rispy.loads(file_data.decode())
        await self.update_status(file_id, Status.INDEXING, process=0)
        # validate and ingest
        done = await self.insert_documents(file_id, documents)
        # vectorization
        await self.update_status(file_id, Status.VECTORIZING, process=0)
        # self.vector_client
        docs = await self.db_client.bntl_coll.find(
            {"_id": {"$in": [bson.objectid.ObjectId(id) for id in done]}}
        ).to_list(length=None)
        
        # done
        await self.update_status(file_id, Status.DONE)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--ris-file', required=True, help="Path to ris file with data to be indexed.")
    args = parser.parse_args()

    from bntl.db import DBClient
    from bntl.vector import VectorClient

    async def main(path):
        vector_client = VectorClient()
        db_client = await DBClient.create()

        async with utils.AsyncLogger() as logger:    
            async with aiofiles.open(path, 'r') as f:
                await logger.log("Loading data from file")
                data = rispy.loads(await f.read())

            # clean db
            await logger.log("Cleaning up MongoDB collections")
            await db_client.bntl_coll.drop()
            await db_client.query_coll.drop()
            await db_client.upload_coll.drop()

            await logger.log("Cleaning up QDrant collections")
            vector_client.qdrant_client.delete_collection(vector_client.collection_name)

            # insert documents
            await logger.log("Inserting {} docs from file: {}".format(len(data), path))

            async def callback(progress):
                await logger.log("Inserted {} from {} documents.".format(progress, len(data)))
            
            done = await insert_documents(
                db_client.bntl_coll, data, logger=logger, progress_callback=callback)
            
            await logger.log("Inserted {} documents with the following ids".format(len(done)))
            await logger.log("[" + ", ".join(['"{}"'.format(id) for id in done]) + "]")
            
            # vectorize
            docs = await db_client.bntl_coll.find(
                {"_id": {"$in": [bson.objectid.ObjectId(id) for id in done]}}
            ).to_list(length=None)

        return done

    done = asyncio.run(main(args.ris_file))



# collection = b_client.mongodb_client1.bntl.test

# docs = [{ '_id': 1 }, { '_id': 1 },{ '_id': 2 }]

# import pymongo
# try:
#     result = await collection.insert_many(docs,ordered=False)

# except pymongo.errors.BulkWriteError as e:
#     print(e.details['writeErrors'])



import bson
import logging
import collections
from datetime import datetime, timezone
from typing import Dict

import bson.objectid
import rispy

from bntl import utils
from bntl.models import StatusModel
from vectorizer import client


logger = logging.getLogger(__name__)


class Status:
    UPLOADING = 'Uploading...'
    INDEXING = 'Indexing...'
    VECTORIZING = 'Vectorizing...'
    UNKNOWNERROR = 'Unknown error'
    UNKNOWNFORMAT = 'Unknown input format'
    VECTORIZINGERROR = 'Error while vectorizing'
    EMPTYFILE = 'Empty input file' # can happen if all documents fail to validate
    DONE = 'Done'

    @classmethod
    def __get_classes__(cls):
        return {key: getattr(cls, key) for key in vars(cls).keys() if not key.startswith('__')}


def get_doc_text(doc) -> Dict[str, str]:
    title = doc.get("title", "")
    if doc.get("secondary_title"):
        title += "; " + doc["secondary_title"]
    if doc.get("tertiary_title"):
        title += "; " + doc["tertiary_title"]
    keywords = None
    if doc.get("keywords"):
        keywords = "; ".join(doc["keywords"])

    return {"title": title, "keywords": keywords}


def convert_to_text(doc, ignore_keywords=False) -> str:
    output = doc.get("title", "") or ""
    if doc["keywords"] and not ignore_keywords:
        output += "; " + doc["keywords"]
    return output


class FileUploadManager:
    def __init__(self, db_client, vector_client) -> None:
        self.file_chunks: Dict[str, Dict[int, bytes]] = collections.defaultdict(dict)
        self.db_client = db_client
        self.vector_client = vector_client

    def add_chunk(self, file_id: str, chunk_number: int, chunk_data: bytes):
        """
        Save chunks in memory
        """
        self.file_chunks[file_id][chunk_number] = chunk_data

    async def update_status(self, file_id, status, **kwargs):
        """
        Utility function to keep track of the task status
        """
        logger.info(f"Received status [{status}] for file {file_id}")
        await self.db_client.update_upload_status(
            file_id, StatusModel(status=status, 
                                 date_updated=datetime.now(timezone.utc),
                                 **kwargs))
        
    async def insert_documents(self, documents, file_id):
        """
        Utility function for document validation and ingestion
        """
        async def callback(progress):
            await self.update_status(file_id, Status.INDEXING, progress=progress/len(documents))
        async with utils.AsyncLogger(utils.get_log_filename(file_id)) as a_logger:
            return await self.db_client.insert_documents(
                documents, logger=a_logger, progress_callback=callback)

    async def process_file(self, file_id: str):
        """
        When upload is finished, this method collects data from memory, validates input documents,
        ingests them into the database, vectorizes them and indexes the vectors.
        """
        async with utils.AsyncLogger(utils.get_log_filename(file_id)) as a_logger:
            # collect data
            await a_logger.info("Collecting data from upload: {}".format(file_id))
            file_data = b''.join([self.file_chunks[file_id][i] for i in range(len(self.file_chunks[file_id]))])
            try:
                documents = rispy.loads(file_data.decode())
            except rispy.parser.ParseError as e:
                await self.update_status(file_id, Status.UNKNOWNFORMAT)
                return
            await a_logger.info("Received {} documents".format(len(documents)))

            # validate and ingest
            await a_logger.info("Indexing data...")
            await self.update_status(file_id, Status.INDEXING, progress=0)
            doc_ids = await self.insert_documents(documents, file_id)
            if len(doc_ids) == 0:
                # no valid documents
                await a_logger.info("Couldn't validate any documents from upload")
                await self.update_status(file_id, Status.EMPTYFILE)
                return

            # vectorization
            await a_logger.info("Vectorizing {} documents...".format(len(doc_ids)))
            await self.update_status(file_id, Status.VECTORIZING, progress=0)
            data = await self.db_client.find({"_id": {"$in": [bson.objectid.ObjectId(id) for id in doc_ids]}})
            vectors = await client.send_vectorizer_task_and_poll(
                file_id, 
                [convert_to_text(get_doc_text(doc), ignore_keywords=True) for doc in data],
                logger=a_logger)
            if vectors:
                await self.vector_client.insert(vectors, [str(doc["_id"]) for doc in data])
                await self.update_status(file_id, Status.DONE)
            else:
                await self.update_status(file_id, Status.VECTORIZINGERROR)

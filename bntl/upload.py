
import logging
import collections
from datetime import datetime, timezone
from typing import Dict

import rispy
from fastapi.concurrency import run_in_threadpool

from bntl import utils
from bntl.models import StatusModel
from bntl.rdf import parse_rdf


logger = logging.getLogger(__name__)


class Status:
    UPLOADING = 'Uploading...'
    PARSING = 'Parsing RDF data...'
    INDEXING = 'Indexing...'
    VECTORIZING = 'Vectorizing...'
    UNKNOWNERROR = 'Unknown error'
    UNKNOWNFORMAT = 'Unknown input format'
    EMPTYFILE = 'Empty input file' # can happen if all documents fail to validate
    DONE = 'Done'

    @classmethod
    def __get_classes__(cls):
        return {key: getattr(cls, key) for key in vars(cls).keys() if not key.startswith('__')}


class FileUploadManager:
    def __init__(self, db_client) -> None:
        self.file_chunks: Dict[str, Dict[int, bytes]] = collections.defaultdict(dict)
        self.db_client = db_client

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
        async with utils.AsyncLogger(utils.get_upload_log_filename(file_id)) as a_logger:
            return await self.db_client.insert_documents(
                documents, logger=a_logger, progress_callback=callback)

    async def process_file_task(self, file_id: str):
        """
        When upload is finished, this method collects data from memory, validates input documents,
        and ingests them into the database. This is a background
        task, and thus we need to process all possible exceptions to avoid silent failing.
        """
        documents = None
        async with utils.AsyncLogger(utils.get_upload_log_filename(file_id)) as a_logger:
            # collect data
            await a_logger.info("Collecting data from upload: {}".format(file_id))
            try:
                file_data = b''.join([self.file_chunks[file_id][i] for i in range(len(self.file_chunks[file_id]))])
                await a_logger.info("Parsing RDF into RIS...")
                await self.update_status(file_id, Status.PARSING)
                ris_data = await run_in_threadpool(lambda: parse_rdf(file_data.decode()))
                await a_logger.info("Parsed")
                await a_logger.info("Loading data...")
                documents = rispy.loads(ris_data, mapping=utils.RISPY_MAPPING)
                await a_logger.info("Received {} documents".format(len(documents)))
            except rispy.parser.ParseError as e:
                await self.update_status(file_id, Status.UNKNOWNFORMAT, detail=str(e))
            except Exception as e:
                await self.update_status(file_id, Status.UNKNOWNFORMAT, detail="Couldn't parse RDF file")
            finally:
                if documents:
                    try:
                        # validate and ingest
                        await a_logger.info("Indexing data...")
                        await self.update_status(file_id, Status.INDEXING, progress=0)
                        doc_ids = await self.insert_documents(documents, file_id)
                        await a_logger.info("Inserted {} documents".format(len(doc_ids)))
                        await a_logger.info("Job done.")
                        await self.update_status(file_id, Status.DONE)
                    except Exception as e:
                        await self.update_status(file_id, Status.UNKNOWNERROR, detail=str(e))
                else:
                    # no valid documents
                    await a_logger.info("Empty file or no valid documents in upload")
                    await self.update_status(file_id, Status.EMPTYFILE)


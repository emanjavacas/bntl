
import collections
from datetime import datetime, timezone
from typing import List, Dict

from pydantic import BaseModel


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


class StatusEntry(BaseModel):
    status: str
    date_updated: datetime


class FileStatus(BaseModel):
    filename: str
    status: str
    history: List[StatusEntry]


class FileUploadManager:
    def __init__(self, app_state) -> None:
        self.file_chunks = Dict[str, Dict[int, bytes]] = collections.defaultdict(dict)
        self.app_state = app_state

    def add_chunk(self, file_id: str, chunk_number: int, chunk_data: bytes):
        self.file_chunks[file_id][chunk_number] = chunk_data

    async def update_status(self, file_id: str, new_status: str):
        self.app_state.bntl_client.update_upload_status(file_id, new_status)

    async def process_file_if_ready(self, file_id: str, total_chunks: int):
        if len(self.file_chunks[file_id]) == total_chunks:
            file_data = b''.join([self.file_chunks[file_id][i] for i in range(total_chunks)])
            # read as ris data
            # validate and ingest
            # send to vectorization
            # done
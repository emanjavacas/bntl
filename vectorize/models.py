
from datetime import datetime, timezone

from typing import Optional, Dict, Any, List
from pydantic import BaseModel


class Status:
    DONE = 'Done!'
    RETRYING = 'Retrying...'
    VECTORIZING = 'Vectorizing...'
    UNKNOWNERROR = 'Unknown error'
    RUNTIMEERROR = "Model runtime error"
    OUTOFATTEMPTS = "Task ran out of attempts" # ran out of attempts accessing GPU memory
    TIMEOUT = "Task timed out" # client code timeout


class StatusModel(BaseModel):
    status: str
    date_created: datetime
    status_info: Optional[Dict[Any, Any]]


def create_new_status(status, **status_info) -> StatusModel:
    return StatusModel(status=status, date_created=datetime.now(timezone.utc), status_info=status_info)


class TaskModel(BaseModel):
    task_id: str
    date_created: datetime
    current_status: StatusModel
    history: Optional[List[StatusModel]] = []


class VectorModel(BaseModel):
    task_id: str
    doc_id: str # doc_id mapping to bntl.doc_id
    vector_id: int # just an integer to index input order
    text: str
    vector: Optional[List[float]] = []


class VectorizeParams(BaseModel):
    task_id: str
    texts: List[str]
    doc_ids: List[str]
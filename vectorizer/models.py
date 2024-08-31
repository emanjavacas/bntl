
from datetime import datetime

from typing import Optional, Dict, Any, List
from pydantic import BaseModel


class Status:
    DONE = 'Done!'
    RETRYING = 'Retrying...'
    VECTORIZING = 'Vectorizing...'
    UNKNOWNERROR = 'Unknown error'
    RUNTIMEERROR = "Model runtime error"
    OUTOFATTEMPTS = 'Task ran out of attempts'


class StatusModel(BaseModel):
    status: str
    date_created: datetime
    status_info: Optional[Dict[Any, Any]]


class TaskModel(BaseModel):
    task_id: str
    date_created: datetime
    current_status: StatusModel
    history: Optional[List[StatusModel]] = []


class VectorModel(BaseModel):
    task_id: str
    vector_id: int
    text: str
    vector: Optional[List[float]] = []

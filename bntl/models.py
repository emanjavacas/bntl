
import uuid
from datetime import datetime

from typing import List, Optional, Dict, Generic, TypeVar, Literal
from pydantic import BaseModel, Field, ConfigDict


T = TypeVar("T")


class EntryModel(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, from_attributes=True)
    # mandatory
    label: str = Field(help="Zotero export validation result")
    name_of_database: str = Field(help="BNTL metadata")
    title: str = Field(help="Title of the record")
    type_of_reference: str = Field(help="Record format")
    year: int = Field(help="Year of record publication in string format")
    end_year: int = Field(help="Custom-made field to deal with range years (e.g. 1987-2024)")
    # optional
    secondary_title: Optional[str] = Field(default=None)
    tertiary_title: Optional[str] = Field(default=None)
    authors: Optional[List[str]] = Field(default=None)
    first_authors: Optional[List[str]] = Field(default=None)
    secondary_authors: Optional[List[str]] = Field(default=None)
    tertiary_authors: Optional[List[str]] = Field(default=None)
    journal_name: Optional[str] = Field(default=None)
    end_page: Optional[str] = Field(default=None)
    start_page: Optional[str] = Field(default=None)
    volume: Optional[str] = Field(default=None)
    number: Optional[str] = Field(default=None)
    edition: Optional[str] = Field(default=None)
    issn: Optional[str] = Field(default=None)
    publisher: Optional[str] = Field(default=None)
    place_published: Optional[str] = Field(default=None)
    urls: Optional[List[str]] = Field(default=None)
    note: Optional[str] = Field(default=None)
    research_notes: Optional[str] = Field(default=None)
    keywords: Optional[List[str]] = Field(default=None)
    unknown_tag: Optional[Dict[str, List[str]]] = Field(default=None)


class DBEntryModel(EntryModel):
    doc_id: str = Field(help='Internal MongoDB id')
    date_added: datetime = Field(help="Date of ingestion")


class VectorEntryModel(DBEntryModel):
    score: float = Field(help="Vector similarity")


class SearchQuery(BaseModel):
    type_of_reference: Optional[str] = None
    title: Optional[str] = None
    year: Optional[str] = None
    author: Optional[str] = None
    keywords: Optional[str] = None
    use_regex_author: Optional[bool] = False
    use_regex_title: Optional[bool] = False
    use_regex_keywords: Optional[bool] = False
    use_case_author: Optional[bool] = False
    use_case_title: Optional[bool] = False
    use_case_keywords: Optional[bool] = False
    full_text: Optional[str] = None


class QueryModel(BaseModel):
    query_id: str
    timestamp: datetime
    search_query: SearchQuery
    session_id: uuid.UUID
    n_hits: Optional[int]
    last_accessed: datetime


class _PagedResponseModel(BaseModel, Generic[T]):
    n_hits: int
    from_page: int
    to_page: int
    total_pages: int
    items: List[T]


class PageParams(BaseModel):
    page: int=Field(default=1, ge=1, help="Page number to retrieve")
    size: int=Field(default=10, le=100, help="Number of documents per page")
    sort_author: Literal["ascending", "descending", ""]=Field(
        default="", help="Sort order for author")
    sort_year: Literal["ascending", "descending", ""]=Field(
        default="", help="Sort order for year")
    

class VectorParams(BaseModel):
    limit: int=Field(default=10, help="Top-k vectors to retrieve")
    threshold: float=Field(default=0, ge=0, lt=1, help="Similarity threshold")


class PagedResponseModel(PageParams, _PagedResponseModel, Generic[T]):
    pass

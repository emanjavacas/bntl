
import uuid
from datetime import datetime
from string import Formatter

from typing import List, Optional, Dict, Generic, TypeVar, Literal, Union, Any
from typing_extensions import Self
from pydantic import BaseModel, Field, ConfigDict, model_validator
from enum import Enum

from rispy.config import TAG_KEY_MAPPING

from bntl import utils


T = TypeVar("T")


def format_str_from_ris(repr_str):
    """
    Substitute RIS fields with the corresponding fields in the parsed document
    """
    for key, value in TAG_KEY_MAPPING.items():
        repr_str = repr_str.replace(key, value)
    return repr_str.replace("[", "{").replace("]", "}")


class DocScreen:
    """
    This class handles required fields on the basis of the screen representation
    """

    # JOUR = "[AU]. [TI]. In: [JO]: [VL] ([PY]) [IS], [SP]-[EP]."
    # BOOK = "[AU]. [TI]. [CY]: [PB], [PY]. [EP] p."
    # BOOK_2EDS = "[A2] (red.). [TI]. [CY]: [PB], [PY]. [EP] p."
    # CHAP = "[A1]. [TI]. In: [A2] (red.). [T2]. [CY]: [PB], [PY], p. [SP]-[EP]."
    # EJOUR = "[AU]. [TI]. Op: [JO]: [VL]."
    # WEB = "[AU]. [TI]. [PY]."
    # JFULL = "[TI]. Speciaal nummer van: [JO]: [VL] ([PY]) [IS], [SP]-[EP]."
    # ADVS = "[AU]. [TI]. [CY]: [PB], [PY]."
    JOUR = "[AU]. [TI]. In: [JO]: [VL] ([PY]) [IS], [SP]-[EP]."
    BOOK = "[AU]. [TI]. [CY]: [PB], [PY]."
    BOOK_2EDS = "[A2] (red.). [TI]. [CY]: [PB], [PY]."
    CHAP = "[A1]. [TI]. In: [A2] (red.). [T2]. [CY]: [PB], [PY], p. [SP]-[EP]."
    EJOUR = "[AU]. [TI]. Op: [JO]: [VL]."
    WEB = "[AU]. [TI]. [PY]."
    JFULL = "[TI]. Speciaal nummer van: [JO]: [VL] ([PY]) [IS], [SP]-[EP]."
    ADVS = "[AU]. [TI]. [CY]: [PB], [PY]."


    @staticmethod
    def get_repr_str(doc):
        """
        Find type of screenname based on document structure
        """
        if doc['type_of_reference'] == "JOUR":
            return DocScreen.JOUR
        elif doc['type_of_reference'] == "BOOK":
            if doc.get('secondary_authors') is not None:
                # ignore authors
                return DocScreen.BOOK_2EDS
            return DocScreen.BOOK
        elif doc['type_of_reference'] == "CHAP":
            return DocScreen.CHAP
        elif doc['type_of_reference'] == "JFULL":
            return DocScreen.JFULL
        elif doc['type_of_reference'] == "WEB":
            return DocScreen.WEB
        elif doc['type_of_reference'] == "ADVS":
            return DocScreen.ADVS
        elif doc['type_of_reference'] == 'EJOUR':
            return DocScreen.EJOUR
        else:
            raise ValueError(f"Unknown publication type: {doc['type_of_reference']}")

    @staticmethod
    def find_missing_fields(doc):
        repr_str = format_str_from_ris(DocScreen.get_repr_str(doc))
        missing = []
        for _, fname, _, _ in Formatter().parse(format_str_from_ris(repr_str)):
            if not fname: continue
            if not doc.get(fname):
                missing.append(fname)
        return missing

    @staticmethod
    def render_doc(doc):
        repr_str = format_str_from_ris(DocScreen.get_repr_str(doc))
        kwargs = {k: utils.maybe_list(v) for k, v in doc.items()}
        return repr_str.format_map(kwargs)


TypeOfReference = Literal["JOUR", "BOOK", "CHAP", "EJOUR", "WEB", "JFULL", "ADVS"]


class EntryModel(BaseModel):
    """
    Entry model on the basis of the 
    """
    model_config = ConfigDict(arbitrary_types_allowed=True, from_attributes=True)
    # this is stored for convenience (enable year range queries)
    end_year: Optional[Union[int|str]] = Field(help="Custom-made field to deal with range years (e.g. 1987-2024)", default="")
    # required
    type_of_reference: TypeOfReference = Field(help="Record format")

    # source fields (fields encountered in first db dump, it may fail)
    title: Optional[str] = Field(help="Title of the record", default=None)
    year: Optional[Union[int|str]] = Field(help="Year of record publication in string format", default="")
    label: Optional[str] = Field(help="Zotero export validation result", default=None)
    name_of_database: Optional[str] = Field(help="BNTL metadata", default=None)
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

    @model_validator(mode="before")
    def check_document_type(self) -> Self:
        missing = DocScreen.find_missing_fields(self)
        if missing:
            raise ValueError({"missing_fields": missing, "repr_type": DocScreen.get_repr_str(self)})
        return self


class DBEntryModel(EntryModel):
    doc_id: str = Field(help='Internal MongoDB id')
    date_added: datetime = Field(help="Date of ingestion")
    hash: str = Field(help="Enable duplicate detection")


class SourceModel(BaseModel):
    doc_id: str = Field(help="Doc id pointing to the EntryModel doc_id")
    source: Dict[Any, Any] = Field(help="Input source for the document in BSON format")


class VectorEntryModel(DBEntryModel):
    score: float = Field(help="Vector similarity")


class QueryParams(BaseModel):
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
    query_params: QueryParams
    session_id: uuid.UUID
    n_hits: Optional[int]
    last_accessed: datetime


class _PagedResponseModel(BaseModel, Generic[T]):
    n_hits: int
    from_page: int
    to_page: int
    total_pages: int
    items: List[T]
    parent_n_hits: Optional[int] = None # n_hits of previous query


class PageParams(BaseModel):
    page: int=Field(default=1, ge=1, help="Page number to retrieve")
    size: int=Field(default=10, le=100, help="Number of documents per page")
    sort_author: Literal["ascending", "descending", ""]=Field(
        default="", help="Sort order for author")
    sort_year: Literal["ascending", "descending", ""]=Field(
        default="", help="Sort order for year")
    

class PagedResponseModel(PageParams, _PagedResponseModel, Generic[T]):
    pass


class VectorParams(BaseModel):
    limit: int=Field(default=10, help="Top-k vectors to retrieve")
    threshold: float=Field(default=0, ge=0, lt=1, help="Similarity threshold")


class StatusModel(BaseModel):
    status: str
    date_updated: Optional[datetime]
    progress: Optional[float] = Field(ge=0, le=1, default=None)
    detail: Optional[Any] = Field(default=None)


class FileUploadModel(BaseModel):
    file_id: str
    filename: str
    date_uploaded: datetime
    current_status: StatusModel
    history: List[StatusModel]


class LoginParams(BaseModel):
    password: str
    next_url: str
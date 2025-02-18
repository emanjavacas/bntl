
import uuid
from datetime import datetime

from typing import List, Optional, Generic, TypeVar, Literal, Any
from pydantic import BaseModel, Field, ConfigDict, EmailStr


def _render_authors(authors):
    output = ""
    if len(authors) == 1:
        output += authors[0]
    elif len(authors) == 2:
        output += " & ".join(authors)
    else:
        output += ", ".join(authors[:-1]) + " & " + authors[-1]
    return output


class AdditiveNode:
    def __init__(self):
        self.next_node = None

    def __add__(self, other):
        """
        Chain nodes together using the `+` operator.

        :param other: Another Node to chain.
        :return: The current Node with the next_node linked.
        """
        if not isinstance(other, AdditiveNode):
            raise TypeError("Can only add another Node instance.")
        current = self
        while current.next_node:
            current = current.next_node
        current.next_node = other
        return self

    def render_this(self, record) -> str:
        raise NotImplementedError
    
    def render(self, record) -> str:
        rendered = self.render_this(record)
        if self.next_node:
            return rendered + self.next_node.render(record)
        return rendered


class Node(AdditiveNode):
    def __init__(self, field, pre="", post="", separator=", ", list_renderer=None):
        """
        Initialize a Node.

        :param field: The field key to extract from the record.
        :param pre: Prefix to add before the field value if it exists.
        :param post: Suffix to add after the field value if it exists.
        :param separator: Separator to use if multiple values exist for the field.
        """
        super().__init__()
        self.field = field
        self.pre = pre
        self.post = post
        self.separator = separator
        self.list_renderer = list_renderer

    def render_this(self, record) -> str:
        """
        Render the field value for this node and any chained nodes.

        :param record: A dictionary representing the RIS record.
        :return: The rendered string for this node and its chain.
        """
        if value := record.get(self.field):
            if isinstance(value, list):
                if self.list_renderer is not None:
                    value = self.list_renderer(value)
                else:
                    value = self.separator.join(value)
            if value.endswith(self.post.strip()):
                value = value.rstrip(self.post)
            return f"{self.pre}{value}{self.post}"
        return ""


class ConditionalNode(AdditiveNode):
    def __init__(self, field1, field2, sep="; ", wrap="()"):
        super().__init__()
        self.field1 = field1
        self.field2 = field2
        self.sep = sep
        self.wrap_left, self.wrap_right = list(wrap)

    def render(self, record):
        rendered = ""
        if (value1 := record.get(self.field1)) and (value2 := record.get(self.field2)):
            rendered = f"{self.wrap_left}{value1}{self.sep}{value2}{self.wrap_right}"
        elif value1 := record.get(self.field1):
            rendered = f"{self.wrap_left}{value1}{self.wrap_right}"
        elif value2 := record.get(self.field2):
            rendered = f"{self.wrap_left}{value2}{self.wrap_right}"
        return rendered


# [A1]. [TI]. In: [JO]: [VL] ([PY]) [IS], [SP]-[EP]. 
JOUR_renderer = (
    Node("first_authors", post=". ", list_renderer=_render_authors) +
    Node("title", post=". ") +
    Node("journal_name", pre="In: ", post=": ") +
    Node("volume", post=" ") +
    Node("year", pre="(", post=") ") +
    Node("number") +
    Node("start_page", pre=", ") +
    Node("end_page", pre="-"))

# [A1]. [TI]. [CY]: [PB], [PY]. [SP] p. ([T2]; [SV]).
BOOK_renderer = (
    Node("first_authors", post=". ", list_renderer=_render_authors) +
    Node("title", post=". ") +
    Node("place_published", post=": ") +
    Node("publisher", post=", ") +
    Node("year", post=". ") +
    Node("start_page", post=" p. ") +
    ConditionalNode("secondary_title", "series_volume", wrap=["(", ")"]))

# [A2] (red.). [TI]. [CY]: [PB], [PY]. [SP] p. ([T2]; [SV]).
BOOK_2EDS_renderer = (
    Node("secondary_authors", post=" (red.). ", list_renderer=_render_authors) +
    Node("title", post=". ") +
    Node("place_published", post=": ") +
    Node("publisher", post=", ") +
    Node("year", post=". ") +
    Node("start_page", post=" p. ") +
    ConditionalNode("secondary_title", "series_volume", wrap=["(", ")"]))

# [A1]. [TI]; [A2] (red.). [CY]: [PB], [PY]. [SP] p. ([T2]; [SV]).
BOOK_A1_2EDS_renderer = (
    Node("first_authors", post=". ", list_renderer=_render_authors) +
    Node("title", post="; ") +
    Node("secondary_authors", post=" (red.). ", list_renderer=_render_authors) +
    Node("place_published", post=": ") +
    Node("publisher", post=", ") +
    Node("year", post=". ") +
    Node("start_page", post=" p. ") +
    ConditionalNode("secondary_title", "series_volume", wrap=["(", ")"]))

# [A1]. [TI]. In: [A2] (red.). [T2]. [CY]: [PB], [PY], p. [SP]-[EP]. ([T3]; [SV]).
CHAP_renderer = (
    Node("first_authors", post=". ", list_renderer=_render_authors) +
    Node("title", post=". In: ") +
    Node("secondary_authors", post=" (red.). ", list_renderer=_render_authors) +
    Node("secondary_title", post=". ") +
    Node("place_published", post=": ") +
    Node("publisher", post=", ") +
    Node("year", post=", ") +
    Node("start_page", pre="p. ") +
    Node("end_page", pre="-", post=". ") +
    ConditionalNode("tertiary_title", "series_volume", wrap=["(", ")"]))

# [A1]. [TI]. [PY].
WEB_renderer = (
    Node("first_authors", post=". ", list_renderer=_render_authors) +
    Node("title", post=". ") +
    Node("year", post="."))

# [TI]. Speciaal nummer van: [T2]: [VL] ([PY]) [SV], [SP] p.
JFULL_renderer = (
    Node("title", post=". ") +
    Node("secondary_title", pre="Speciaal nummer van: ", post=": ") +
    Node("volume", post=" ") +
    Node("year", pre="(", post=")") +
    Node("series_volume", pre=" ") +
    Node("start_page", pre=", ", post=" p"))

# [AU]. [TI]. [PB], [PY].
ADVS_renderer = (
    Node("first_authors", post=". ", list_renderer=_render_authors) +
    Node("title", post=". ") +
    Node("publisher", post=", ") +
    Node("year"))


def get_record_screen_name(record):
    if record["type_of_reference"] == "JOUR":
        output = JOUR_renderer.render(record)
    elif record["type_of_reference"] == "BOOK":
        if record.get("secondary_authors"):
            if record.get("first_authors"):
                output = BOOK_A1_2EDS_renderer.render(record)
            else:
                output = BOOK_2EDS_renderer.render(record)
        else:
            output = BOOK_renderer.render(record)
    elif record["type_of_reference"] == "CHAP":
        output = CHAP_renderer.render(record)
    elif record["type_of_reference"] == "WEB":
        output = WEB_renderer.render(record)
    elif record["type_of_reference"] == "JFULL":
        output = JFULL_renderer.render(record)
    elif record["type_of_reference"] == "ADVS":
        output = ADVS_renderer.render(record)
    else:
        raise ValueError("Unknown reference type: {}".format(record["type_of_reference"]))

    output = output.strip()
    if not output.endswith("."):
        output += '.'
    return output


TypeOfReference = Literal["JOUR", "BOOK", "CHAP", "WEB", "JFULL", "ADVS"]


class DocumentModel(BaseModel):
    """
    Document as it comes in from the ris parser
    """
    model_config = ConfigDict(arbitrary_types_allowed=True, from_attributes=True)
    # mandatory
    id: str = Field(help="Zotero ID") # ID
    type_of_reference: TypeOfReference = Field(help="Record format") # TY
    # optional
    keywords: Optional[List[str]] = Field(help="Keywords", default=None) # KW
    first_authors: Optional[List[str]] = Field(help="Authors", default=None) # A1
    secondary_authors: Optional[List[str]] = Field(help="Editor", default=None) # A2
    tertiary_authors: Optional[List[str]] = Field(help="Translator", default=None) # A3
    title: Optional[str] = Field(help="Title", default=None) # T1
    secondary_title: Optional[str] = Field(help="Book Title/Series", default=None) # T2
    tertiary_title: Optional[str] = Field(help="Series/Special issue", default=None) # T3
    notes_abstract: Optional[str] = Field(help="Old BNTL citation", default=None) # N2
    start_page: Optional[str] = Field(help="Start page", default=None) # SP
    end_page: Optional[str] = Field(help="End page", default=None) # EP
    year: Optional[str] = Field(help="Publication year", default=None) # PY
    access_date: Optional[str] = Field(help="Date added", default=None) # Y2
    number: Optional[str] = Field(help="Issue", default=None) # IS
    journal_name: Optional[str] = Field(help="Journal name", default=None) # JO
    issn: Optional[str] = Field(help="ISSN", default=None) # SN
    volume: Optional[str] = Field(help="Volume", default=None) # VL
    series_volume: Optional[str] = Field(help="Series Volume", default=None) # SV
    abstract: Optional[str] = Field(help="Additional Information", default=None) # AB
    reviewed_item: Optional[str] = Field(help="Review of", default=None) # RI
    research_notes: Optional[str] = Field(help="Review", default=None) # RN
    urls: Optional[List[str]] = Field(help="URL", default=None) # UR
    # SV: Optional[str] = Field(help="Series number", default=None)
    publisher: Optional[str] = Field(help="Publisher", default=None) # PB
    place_published: Optional[str] = Field(help="Place", default=None) # CY
    edition: Optional[str] = Field(help="Edition", default=None) # ET
    doi: Optional[str] = Field(help="DOI", default=None) # DO


class ComputedFields(BaseModel):
    start_year: Optional[int] = Field(default=None)
    end_year: Optional[int] = Field(default=None)


class DBDocumentModel(BaseModel):
    document: DocumentModel
    computed_fields: ComputedFields
    date_added: datetime = Field(help="Date of ingestion")
    is_oa: bool = Field(help="Whether the document is oa, based on whether it has valid url")


class VectorEntryModel(DBDocumentModel):
    score: float = Field(help="Vector similarity")


class QueryParams(BaseModel):
    type_of_reference: Optional[str] = None
    title: Optional[str] = None
    year: Optional[str] = None
    author: Optional[str] = None
    keywords: Optional[str] = None
    is_oa: Optional[bool] = False
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


T = TypeVar("T")


class _PagedResponseModel(BaseModel, Generic[T]):
    n_hits: int
    from_page: int
    to_page: int
    total_pages: int
    items: List[T]
    parent_n_hits: Optional[int] = None # n_hits of previous query


class PageParams(BaseModel):
    page: int = Field(default=1, ge=1, help="Page number to retrieve")
    size: int = Field(default=10, le=100, help="Number of documents per page")
    sort_author: Literal["ascending", "descending", ""] = Field(default="", help="Sort order for author")
    sort_year: Literal["ascending", "descending", ""] = Field(default="", help="Sort order for year")
    

class PagedResponseModel(PageParams, _PagedResponseModel, Generic[T]):
    pass


class VectorParams(BaseModel):
    limit: int = Field(default=10, help="Top-k vectors to retrieve")
    threshold: float = Field(default=0, ge=0, lt=1, help="Similarity threshold")


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


class VectorizationTaskModel(BaseModel):
    task_id: str
    date_started: datetime
    current_status: StatusModel
    history: List[StatusModel]


class LoginParams(BaseModel):
    password: str
    next_url: str


class LoginMailParams(BaseModel):
    mail: EmailStr


class LoginCodeParams(BaseModel):
    code: str
    next_url: str
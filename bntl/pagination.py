
import math
from typing import Generic, List, TypeVar, Literal

import pymongo
from pydantic import BaseModel, Field
from bntl.queries import SearchQuery


T = TypeVar("T")
SORT_ORDER_MAP = {"ascending": pymongo.ASCENDING, "descending": pymongo.DESCENDING}


class PagedResponseSchema(BaseModel, Generic[T]):
    n_hits: int
    from_page: int
    to_page: int
    total_pages: int
    items: List[T]


class PageParams(BaseModel):
    page: int=Field(default=1, ge=1)
    size: int=Field(default=10, le=100)
    sort_author: Literal["ascending", "descending", ""]=Field(default="")
    sort_year: Literal["ascending", "descending", ""]=Field(default="")


class PagedResponseSchemaOut(PageParams, PagedResponseSchema, Generic[T]):
    pass


def parse_sort(page_params: PageParams):
    sort_author, sort_year = page_params.sort_author, page_params.sort_year
    sort = []
    if sort_author:
        sort.append(('author', SORT_ORDER_MAP[sort_author]))
    if sort_year:
        sort.append(('year', SORT_ORDER_MAP[sort_year]))
    return sort


def paginate_find(coll, query: SearchQuery, page_params: PageParams):
    # unwrap params
    page, size = page_params.page, page_params.size

    cursor = coll.find(query)
    sort = parse_sort(page_params)
    results = (cursor.sort(sort) if sort else cursor).skip((page - 1) * size).limit(size)

    # collect information
    n_hits = coll.count_documents(query)

    return results, n_hits


def paginate_aggregate(coll, query: SearchQuery, page_params: PageParams):
    # unwrap params
    page, size = page_params.page, page_params.size

    # https://stackoverflow.com/questions/48305624/how-to-use-mongodb-aggregation-for-pagination
    pipeline = [
        {"$search": {"index": "default", 
                     "text": {"query": query["full_text"], "path": {"wildcard": "*"}}}}]
    sort = dict(parse_sort(page_params))
    if sort:
        pipeline.append({"$sort": sort})
    pipeline += [
        {"$setWindowFields": {"output": {"totalCount": {"$count": {}}}}},
        {"$skip": (page - 1) * size},
        {"$limit": size}]
    cursor = coll.aggregate(pipeline)
    results = list(cursor)

    n_hits = 0
    if len(results) > 0:
        n_hits = results[0]['totalCount']
    for item in results:
        item.pop('totalCount')

    return results, n_hits


def paginate(coll, query: SearchQuery, page_params: PageParams, ResponseSchema: BaseModel) -> PagedResponseSchemaOut[T]:
    # unwrap params
    page, size = page_params.page, page_params.size
    sort_author, sort_year = page_params.sort_author, page_params.sort_year

    # search and sort
    if "full_text" in query and query["full_text"] is not None:
        results, n_hits = paginate_aggregate(coll, query, page_params)
    else:
        results, n_hits = paginate_find(coll, query, page_params)

    total_pages = math.ceil(n_hits / size)
    from_page = max(1, page - 4)
    to_page = min(total_pages, page + 4)

    return PagedResponseSchemaOut(
        n_hits=n_hits,
        from_page=from_page,
        to_page=to_page,
        total_pages=total_pages,
        sort_author=sort_author,
        sort_year=sort_year,
        page=page,
        size=size,
        items=[ResponseSchema.model_validate(item) for item in results])
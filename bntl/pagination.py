
import math
from typing import Callable

import pymongo
from pydantic import BaseModel

from bntl.models import PageParams, PagedResponseModel, SearchQuery, T
from bntl import utils


SORT_ORDER_MAP = {"ascending": pymongo.ASCENDING, "descending": pymongo.DESCENDING}


def parse_sort(page_params: PageParams):
    """
    Transforms page_params into a pymongo-ready data-structure
    """
    sort_author, sort_year = page_params.sort_author, page_params.sort_year
    sort = []
    if sort_author:
        sort.append(('author', SORT_ORDER_MAP[sort_author]))
    if sort_year:
        sort.append(('year', SORT_ORDER_MAP[sort_year]))
    return sort


def paginate_find(coll, query: SearchQuery, page_params: PageParams):
    """
    Pagination logic over a regular advanced search
    """
    # unwrap params
    page, size = page_params.page, page_params.size

    cursor = coll.find(query)
    sort = parse_sort(page_params)
    results = (cursor.sort(sort) if sort else cursor).skip((page - 1) * size).limit(size)

    # collect information
    n_hits = coll.count_documents(query)

    return results, n_hits


def _paginate_full_text_atlas(coll, query, page_params):
    """
    Internal pagination logic when using cloud atlas for full-text search
        https://www.mongodb.com/products/platform/atlas-search
    """
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


def _paginate_full_text_mongodb(coll, query, page_params):
    """
    Pagination logic for full text search using a local mongodb text index
    (see "bntl.db.create_text_index")
    """
    return paginate_find(coll, {"$text": {"$search": query["full_text"]}}, page_params)


def paginate_full_text(coll, query: SearchQuery, page_params: PageParams):
    """
    Router for the full text functionality
    """
    uri, _ = coll.database.client.address
    if utils.is_atlas(uri):
        return _paginate_full_text_atlas(coll, query, page_params)
    return _paginate_full_text_mongodb(coll, query, page_params)


def paginate(coll, 
             query: SearchQuery, 
             page_params: PageParams, 
             ResponseModel: BaseModel, 
             transform: Callable=utils.identity) -> PagedResponseModel[T]:
    """
    Generic pagination function over MongoDB
    """
    # unwrap params
    page, size = page_params.page, page_params.size
    sort_author, sort_year = page_params.sort_author, page_params.sort_year

    # search and sort
    if "full_text" in query and query["full_text"] is not None:
        # TODO: route to the local method (no atlas)
        results, n_hits = paginate_full_text(coll, query, page_params)
    else:
        results, n_hits = paginate_find(coll, query, page_params)

    total_pages = math.ceil(n_hits / size)
    from_page = max(1, page - 4)
    to_page = min(total_pages, page + 4)

    items = []
    for item in results:
        item["doc_id"] = str(item["_id"])
        item.pop("_id")
        items.append(ResponseModel.model_validate(transform(item)))

    return PagedResponseModel(
        n_hits=n_hits,
        from_page=from_page,
        to_page=to_page,
        total_pages=total_pages,
        sort_author=sort_author,
        sort_year=sort_year,
        page=page,
        size=size,
        items=items)
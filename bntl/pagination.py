
import math
from typing import Callable, List, Dict

import pymongo
from bson.objectid import ObjectId
from pydantic import BaseModel

from bntl.models import PageParams, PagedResponseModel, QueryParams, T
from bntl import utils
from bntl.settings import settings


SORT_ORDER_MAP = {"ascending": pymongo.ASCENDING, "descending": pymongo.DESCENDING}


def build_query(type_of_reference=None,
                title=None,
                year=None,
                author=None,
                keywords=None,
                use_regex_title=False,
                use_case_title=False,
                use_regex_author=False,
                use_case_author=False,
                use_regex_keywords=False,
                use_case_keywords=False,
                full_text=None) -> Dict:
    """
    Transform an incoming query into a MongoDB-ready query
    """

    if full_text:
        return {"$text": {"$search": full_text}}

    query = []

    if type_of_reference is not None:
        query.append({"type_of_reference": type_of_reference})

    if title is not None:
        if use_regex_title:
            title = {"$regex": title}
            if not use_case_title:
                title["$options"] = "i"
        query.append({"$or": [{"title": title},
                              {"secondary_title": title},
                              {"tertiary_title": title}]})

    if year is not None:
        if "-" in year: # year range
            start, end = year.split('-')
            start, end = int(start), int(end)
            query.append({"$or": [{"$and": [{"year": {"$gte": start}},
                                            {"year": {"$lt": end}}]},
                                  {"$and": [{"end_year": {"$gte": start}},
                                            {"end_year": {"$lt": end}}]}]})
        else:
            query.append({"$and": [{"year": {"$gte": int(year)}},
                                   {"end_year": {"$lte": int(year) + 1}}]})

    if author is not None:
        if use_regex_author:
            author = {"$regex": author}
            if not use_case_author:
                author["$options"] = "i"
        query.append({"$or": [{"authors": author},
                              {"first_authors": author},
                              {"secondary_authors": author},
                              {"tertiary_authors": author}]})

    if keywords is not None:
        if use_regex_keywords:
            keywords = {"$regex": keywords}
            if not use_case_keywords:
                keywords["$options"] = "i"
        query.append({"keywords": keywords})

    if len(query) > 1:
        query = {"$and": query}
    elif len(query) == 1:
        query = query[0]
    else:
        query = {}

    return query


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


async def paginate(coll,
                   query_params: QueryParams,
                   page_params: PageParams,
                   ResponseModel: BaseModel,
                   within_ids: List[ObjectId]=None,
                   transform: Callable=utils.identity,
                   **kwargs) -> PagedResponseModel[T]:
    """
    Generic pagination function over MongoDB
    """
    # prepare query
    query = build_query(**query_params.model_dump())
    if within_ids:
        query["_id"] = {"$in": within_ids}
    cursor = coll.find(query)

    # unwrap params
    page, size = page_params.page, page_params.size
    sort_author, sort_year = page_params.sort_author, page_params.sort_year

    # sort
    sort = parse_sort(page_params)
    if sort:
        cursor = cursor.sort(sort)
    else: # sort by descending year by default
        cursor = cursor.sort([('year', pymongo.DESCENDING)])
    results = await cursor.skip((page - 1) * size).limit(size).to_list(length=None)

    # transform output
    items = []
    for item in results:
        item["doc_id"] = str(item.pop("_id"))
        items.append(ResponseModel.model_validate(transform(item)))

    # collect information
    n_hits = await coll.count_documents(query)
    total_pages = math.ceil(n_hits / size)
    from_page = max(1, page - 4)
    to_page = min(total_pages, page + 4)

    return PagedResponseModel(
        n_hits=n_hits,
        from_page=from_page,
        to_page=to_page,
        total_pages=total_pages,
        sort_author=sort_author,
        sort_year=sort_year,
        page=page,
        size=size,
        items=items,
        **kwargs)


async def paginate_within(coll, 
                          original_query: QueryParams,
                          within_query: str, 
                          page_params: PageParams, 
                          ResponseModel: BaseModel,
                          transform: Callable=utils.identity) -> PagedResponseModel[T]:
    """
    Recursive search over a previous search
    """
    # run original query
    results = await coll.find(
        build_query(**original_query.model_dump())
    ).to_list(length=settings.WITHIN_MAX_RESULTS)

    # create within query
    doc_ids = [item["_id"] for item in results]
    query_params = QueryParams(full_text=within_query)

    return await paginate(coll, query_params, page_params, ResponseModel, 
                          within_ids=doc_ids, transform=transform,
                          parent_n_hits=len(results))
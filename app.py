
from typing import List
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi_pagination import Page, add_pagination
from fastapi_pagination.ext.pymongo import paginate

from bntl.db_client import AtlasClient, DBEntryModel
from bntl.settings import settings, setup_logger


setup_logger()
logger = logging.getLogger(__name__)


description = """
## Introduction

Search engine + front end for a Zotero database
"""

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_client = AtlasClient()
    yield
    app.state.db_client.close()


app = FastAPI(
    title="BNTL", 
    description=description,
    summary="BNTL database server application",
    version="0.0.0",
    lifespan=lifespan)


@app.get("/")
async def index():
    return {"message": {"Estimated document count": len(app.state.db_client)}}


@app.get("/query")
async def query(type_of_reference=None, 
                title=None,
                year=None,
                author=None, 
                keywords=None,
                # regex
                use_regex_title=False,
                use_regex_author=False,
                use_regex_keywords=False,
                # limits
                limit=100,
                skip=0) -> List[DBEntryModel]:

    query = []

    if type_of_reference is not None:
        query.append({"type_of_reference": type_of_reference})

    if title is not None:
        title = title if not use_regex_title else {"$regex": title}
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
            query.append({"$and": [{"year": {"$gte": year}},
                                   {"end_year": {"$lt": year}}]})
            
    if author is not None:
        author = author if not use_regex_author else {"$regex": author}
        query.append({"$or": [{"authors": author},
                              {"first_authors": author},
                              {"secondary_authors": author},
                              {"tertiary_authors": author}]})
        
    if keywords is not None:
        keywords = keywords if not use_regex_keywords else {"$regex": keywords}
        query.append({"keywords": keywords})

    if len(query) > 1:
        query = {"$and": query}
    elif len(query) == 1:
        query = query[0]
    else:
        query = {}

    logger.info(query)

    cursor = app.state.db_client.find(query, limit=limit, skip=skip)
    items = list(cursor)
    # drop object id's
    for item in items:
        item.pop('_id')

    return items


# API
# - GET
#   - num records
#   - query
#     - return number of records for query
#     - return records from x to y
#   - fuzzy query
#     - return similar documents to a given document
# - PUSH
#   - insert records (avoiding duplicates)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    import uvicorn
    uvicorn.run("app:app",
                host='0.0.0.0',
                port=settings.PORT,
                # workers=3,
                reload=args.debug)
    

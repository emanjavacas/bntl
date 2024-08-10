
import json
import logging
from typing import List, Optional
from contextlib import asynccontextmanager

from pydantic import BaseModel, Field

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi_pagination import add_pagination
from fastapi_pagination.links import Page
from fastapi_pagination.ext.pymongo import paginate

from bntl.db_client import AtlasClient, EntryModel
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


# mount static folder
app.mount("/static", StaticFiles(directory="static", html=True), name="static")
# add pagination
add_pagination(app)
# declare templates
templates = Jinja2Templates(directory="static")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    return templates.TemplateResponse("about.html", {"request": request})


@app.get("/help", response_class=HTMLResponse)
async def about(request: Request):
    return templates.TemplateResponse("help.html", {"request": request})


@app.get("/search", response_class=HTMLResponse)
async def search(request: Request):
    return templates.TemplateResponse(
        "search.html", 
        {"request": request, 
         "type_of_reference": app.state.db_client.UNIQUE_REFS})


@app.get("/count")
async def index():
    return {"message": {"Estimated document count": len(app.state.db_client)}}    


def build_query(type_of_reference=None,
                title=None,
                year=None,
                author=None,
                keywords=None,
                use_regex_title=False,
                use_regex_author=False,
                use_regex_keywords=False):

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

    return query


class SearchQuery(BaseModel):
    type_of_reference: Optional[str] = None
    title: Optional[str] = None
    year: Optional[str] = None
    author: Optional[str] = None
    keywords: Optional[str] = None
    use_regex_author: Optional[bool] = False
    use_regex_title: Optional[bool] = False
    use_regex_keywords: Optional[bool] = False


@app.post("/query")
async def query(search_query: SearchQuery, 
                limit: int=100, 
                skip: int=0) -> List[EntryModel]:
    query = build_query(**search_query.dict())
    logger.info(query)
    cursor = app.state.db_client.find(query, limit=limit, skip=skip)
    return list(cursor)


@app.post("/paginate")
async def paginate_route(search_query: SearchQuery, request: Request) -> Page[EntryModel]:
    logger.info(search_query)
    query = build_query(**search_query.dict())
    logger.info(query)
    return paginate(app.state.db_client.bntl_coll, query)


@app.get("/results", response_class=HTMLResponse)
async def results(request: Request, search_query: SearchQuery):
    logger.info(search_query)
    query = build_query(**search_query.dict())
    logger.info(query)
    data = paginate(app.state.db_client.bntl_coll, query)
    return templates.TemplateResponse("results.html", {"request": request, **data.dict()})


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


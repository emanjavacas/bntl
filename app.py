
import logging
from typing import List
from contextlib import asynccontextmanager
from bson import ObjectId
import uuid

from fastapi import FastAPI, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from bntl.db import BNTLClient, EntryModel, QueryClient
from bntl.queries import SearchQuery, build_query
from bntl.settings import settings, setup_logger
from bntl.pagination import paginate


setup_logger()
logger = logging.getLogger(__name__)


description = """
## Introduction

Search engine + front end for a Zotero database
"""

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.bntl_client = BNTLClient()
    app.state.query_client = QueryClient()
    yield
    app.state.bntl_client.close()
    app.state.query_client.close()


app = FastAPI(
    title="BNTL", 
    description=description,
    summary="BNTL database server application",
    version="0.0.0",
    lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"])

# mount static folder
app.mount("/static", StaticFiles(directory="static", html=True), name="static")
# declare templates
templates = Jinja2Templates(directory="static")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    return templates.TemplateResponse("about.html", {"request": request})


@app.get("/help", response_class=HTMLResponse)
async def help(request: Request):
    return templates.TemplateResponse("help.html", {"request": request})


@app.get("/search", response_class=HTMLResponse)
async def search(request: Request):
    return templates.TemplateResponse(
        "search.html", 
        {"request": request, 
         "type_of_reference": app.state.bntl_client.unique_refs})


@app.get("/count")
async def index():
    return {"message": {"Estimated document count": len(app.state.bntl_client)}}    


@app.post("/query")
async def query(search_query: SearchQuery, limit: int=100, skip: int=0) -> List[EntryModel]:
    query = build_query(**search_query.dict())
    logger.info(query)
    cursor = app.state.bntl_client.find(query, limit=limit, skip=skip)
    return list(cursor)


@app.post("/registerQuery")
async def register_query(search_query: SearchQuery):
    query_id = app.state.query_client.coll.insert_one(search_query.dict()).inserted_id
    logger.info("Registering query: {}".format(str(query_id)))
    return JSONResponse(content={"query_id": str(query_id)})


@app.get("/paginate")
async def paginate_route(query_id: str, request: Request, page: int=Query(1, ge=1), size: int=Query(10, le=100)):
    search_query = app.state.query_client.coll.find_one({'_id': ObjectId(query_id)})
    logger.info(search_query)
    if not search_query:
        return JSONResponse(status_code=404, content={"error": "Query not found"})
    search_query.pop('_id')
    query = build_query(**search_query)
    logger.info(query)
    results = paginate(app.state.bntl_client.coll, query, EntryModel, page=page, size=size)
    return templates.TemplateResponse(
        "results.html",
        {"request": request, "query_id": query_id, **results.dict()})


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
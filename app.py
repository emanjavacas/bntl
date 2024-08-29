
import bson
import logging
from typing import List
import urllib.parse
from datetime import datetime, timezone
from contextlib import asynccontextmanager
import uuid
import bson.objectid
import humanize

from fastapi import FastAPI, Request, Depends, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from bntl.db import DBClient, build_query
from bntl.vector import VectorClient
from bntl.models import SearchQuery, DBEntryModel, VectorEntryModel, VectorParams
from bntl.settings import settings, setup_logger
from bntl.pagination import paginate, PageParams
from bntl.upload import Status


setup_logger()
logger = logging.getLogger(__name__)


DESCRIPTION = """
## Introduction

Search engine + front end for a Zotero database
"""

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.bntl_client = await DBClient.create()
    app.state.vector_client = VectorClient()
    yield
    app.state.bntl_client.close()
    app.state.vector_client.close()


app = FastAPI(
    title="BNTL", 
    description=DESCRIPTION,
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
templates = Jinja2Templates(directory="static/templates")
templates.env.filters["naturaltime"] = humanize.naturaltime


@app.middleware("http")
async def add_session_id(request: Request, call_next):
    session_id = request.cookies.get("session_id")

    if not session_id:
        session_id = str(uuid.uuid4())
        response = await call_next(request)
        response.set_cookie(key="session_id", value=session_id, httponly=True, samesite="Lax")
    else:
        response = await call_next(request)

    return response


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """
    Home route
    """
    return templates.TemplateResponse(
        "index.html", 
        {"request": request, "last_added": await app.state.bntl_client.find_last_added()})


@app.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    """
    About route
    """
    return templates.TemplateResponse("about.html", {"request": request})


@app.get("/help", response_class=HTMLResponse)
async def help(request: Request):
    """
    Help route showing information about the functioning of the app
    """
    return templates.TemplateResponse("help.html", {"request": request})


@app.get("/search", response_class=HTMLResponse)
async def search(request: Request):
    """
    Search route that shows the search interface
    """
    return templates.TemplateResponse(
        "search.html", 
        {"request": request, 
         "type_of_reference": app.state.bntl_client.unique_refs})


@app.post("/registerQuery")
async def register_query(search_query: SearchQuery, request: Request):
    """
    Log a query and store the parameters so that we can later show it in the query history
    """
    session_id = request.cookies.get("session_id")
    query_data = app.state.bntl_client.find_query(session_id, search_query)
    if query_data:
        query_id = query_data["_id"]
    else:
        query_id = app.state.bntl_client.register_query(session_id, search_query)

    return JSONResponse(content={"query_id": str(query_id)})


async def run_query(search_query: SearchQuery, page_params: PageParams):
    """
    General query logic for all incoming browser search activity
    """
    if not isinstance(search_query, dict):
        search_query = search_query.model_dump()
    query = build_query(**search_query)
    logger.info(query)
    return await paginate(app.state.bntl_client.bntl_coll, query, page_params, DBEntryModel)


@app.get("/quickQuery")
async def quick_query(request: Request,
                      search_query: SearchQuery=Depends(),
                      page_params: PageParams=Depends()):
    """
    Shortcut query route for the database without registering queries in the db.
    It is only meant to be used in quick-queries like links pointing to authors or keywords.
    """
    logger.info(page_params)
    results = await run_query(search_query, page_params)
    # add source
    source = "/quickQuery?" + urllib.parse.urlencode(dict(request.query_params))
    return templates.TemplateResponse(
        "results.html", {"request": request, "source": source, **results.model_dump()})


@app.get("/paginate")
async def paginate_route(query_id: str, request: Request,
                         page_params: PageParams=Depends()):
    """
    Paginate route when moving forward and backward on a given query
    """
    session_id = request.cookies.get("session_id")
    query_data = await app.state.bntl_client.get_query(query_id, session_id)
    if not query_data:
        return JSONResponse(status_code=404, content={"error": "Query not found"})

    results = await run_query(query_data['search_query'], page_params)

    # store total on query database for preview & last accessed
    app.state.bntl_client.update_query(
        query_id, session_id, 
        {"n_hits": results.n_hits, "last_accessed": datetime.now(timezone.utc)})
    
    source = f"/paginate?query_id={query_id}"
    logger.info(source)

    return templates.TemplateResponse(
        "results.html",
        {"request": request, "source": source, **results.model_dump()})


@app.get("/vectorQuery")
async def vector_query(doc_id: str, request: Request, page_params: PageParams=Depends(), vector_params: VectorParams=Depends()):
    """
    Vector-based query route using the document id
    """
    logger.info(vector_params)
    hits = app.state.vector_client.search(doc_id, limit=vector_params.limit)
    hits_mapping = {item["doc_id"]: item["score"] for item in hits}

    def transform(item):
        item["score"] = hits_mapping[item["doc_id"]]
        return item

    query = {"_id": {"$in": [bson.objectid.ObjectId(item["doc_id"]) for item in hits]}}
    # overwrite pagination, since we are not using it for now
    page_params.size = 100
    results = await paginate(app.state.bntl_client.bntl_coll, query, page_params, VectorEntryModel, transform)

    # ensure we sort by score unless differently specified
    if not page_params.sort_author and not page_params.sort_year:
        results.items = sorted(results.items, key=lambda item: hits_mapping[item.doc_id], reverse=True)

    # add source
    source = "/vectorQuery?doc_id=" + doc_id
    return templates.TemplateResponse(
        "results.html", {"request": request, "source": source, **results.model_dump()})


@app.get("/history")
async def history(request: Request):
    """
    Query history route
    """
    session_id = request.cookies.get("session_id")
    return templates.TemplateResponse(
        "history.html",
        {"request": request, "queries": await app.state.bntl_client.get_session_queries(session_id)})


@app.get("/item")
async def item(doc_id: str, request: Request):
    item = app.state.bntl_client.find_one(doc_id)
    return templates.TemplateResponse(
        "item.html", {"request": request, "item": item})


@app.get("/count")
async def index():
    """
    Unexposed route for document count
    """
    return {"message": {"Estimated document count": len(app.state.bntl_client)}}


@app.post("/query")
async def query_route(search_query: SearchQuery, limit: int=100, skip: int=0) -> List[DBEntryModel]:
    """
    Unexposed route for querying the database
    """
    query = build_query(**search_query.model_dump())
    logger.info(query)
    cursor = app.state.bntl_client.find(query, limit=limit, skip=skip)
    return list(cursor)


@app.post("/upload")
async def upload(file: UploadFile = File(...), background_tasks: BackgroundTasks=None):
    # handle upload and process the file in the background
    pass


@app.get("/{}".format(settings.UPLOAD_SECRET), response_class=HTMLResponse)
async def upload_page(request: Request):
    """
    Upload route
    """
    return templates.TemplateResponse("upload.html", {"request": request, "statuses": Status.__get_classes__()})



if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    import uvicorn
    uvicorn.run("app:app",
                host='0.0.0.0',
                port=settings.PORT,
                workers=settings.WORKERS,
                reload=args.debug)

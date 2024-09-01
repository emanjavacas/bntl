
import io
import os
import bson
import logging
from typing import List
import urllib.parse
from datetime import datetime, timezone
from contextlib import asynccontextmanager
import uuid
import bson.objectid
import humanize
import aiofiles

from fastapi import FastAPI, Request, Depends
from fastapi import UploadFile, File, BackgroundTasks, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from bntl.db import DBClient, build_query
from bntl.vector import VectorClient, MissingVectorException
from bntl.models import QueryParams, DBEntryModel, VectorEntryModel, VectorParams, FileUploadModel
from bntl.settings import settings, setup_logger
from bntl.pagination import paginate, PageParams
from bntl.upload import Status, FileUploadManager, convert_to_text, get_doc_text
from bntl.model_manager import ModelManager
from bntl import utils


setup_logger()
logger = logging.getLogger(__name__)


DESCRIPTION = """
## Introduction

Search engine + front end for a Zotero database
"""

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_client = await DBClient.create()
    app.state.vector_client = VectorClient()
    app.state.model_manager = ModelManager()
    app.state.file_upload = FileUploadManager(
        app.state.db_client, 
        app.state.vector_client, 
        app.state.model_manager)
    yield
    app.state.db_client.close()
    await app.state.vector_client.close()
    app.state.model_manager.close()


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
        {"request": request, 
         "total_documents": await app.state.db_client.count(), 
         "last_added": await app.state.db_client.find_last_added()})


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
         "type_of_reference": app.state.db_client.unique_refs})


@app.post("/registerQuery")
async def register_query(query_params: QueryParams, request: Request):
    """
    Log a query and store the parameters so that we can later show it in the query history
    """
    session_id = request.cookies.get("session_id")
    query_data = await app.state.db_client.find_query(session_id, query_params)
    if query_data:
        query_id = query_data["_id"]
    else:
        query_id = await app.state.db_client.register_query(session_id, query_params)

    return JSONResponse(content={"query_id": str(query_id)})


async def run_query(query_params: QueryParams, page_params: PageParams):
    """
    General query logic for all incoming browser search activity
    """
    if not isinstance(query_params, dict):
        query_params = query_params.model_dump()
    query = build_query(**query_params)
    logger.info(query)
    return await paginate(app.state.db_client.bntl_coll, query, page_params, DBEntryModel)


@app.get("/quickQuery")
async def quick_query(request: Request,
                      query_params: QueryParams=Depends(),
                      page_params: PageParams=Depends()):
    """
    Shortcut query route for the database without registering queries in the db.
    It is only meant to be used in quick-queries like links pointing to authors or keywords.
    """
    logger.info(page_params)
    results = await run_query(query_params, page_params)
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
    query_data = await app.state.db_client.get_query(query_id, session_id)
    if not query_data:
        return JSONResponse(status_code=404, content={"error": "Query not found"})

    results = await run_query(query_data['query_params'], page_params)
    # store total on query database for preview & last accessed
    await app.state.db_client.update_query(
        query_id, session_id, 
        {"n_hits": results.n_hits, "last_accessed": datetime.now(timezone.utc)})

    return templates.TemplateResponse(
        "results.html",
        {"request": request, "source": f"/paginate?query_id={query_id}", **results.model_dump()})


@app.get("/vectorQuery")
async def vector_query(doc_id: str, request: Request, page_params: PageParams=Depends(), vector_params: VectorParams=Depends()):
    """
    Vector-based query route using the document id
    """
    logger.info(vector_params)
    try:
        hits = await app.state.vector_client.search(doc_id, limit=vector_params.limit)
    except MissingVectorException as e:
        raise HTTPException(status_code=404, detail=str(e))

    hits_mapping = {item["doc_id"]: item["score"] for item in hits}

    def transform(item):
        item["score"] = hits_mapping[item["doc_id"]]
        return item

    query = {"_id": {"$in": [bson.objectid.ObjectId(item["doc_id"]) for item in hits]}}
    # overwrite pagination, since we are not using it for now
    page_params.size = 100
    results = await paginate(app.state.db_client.bntl_coll, query, page_params, VectorEntryModel, transform)

    # ensure we sort by score unless differently specified
    if not page_params.sort_author and not page_params.sort_year:
        results.items = sorted(results.items, key=lambda item: hits_mapping[item.doc_id], reverse=True)

    # add source
    source = "/vectorQuery?doc_id=" + doc_id
    return templates.TemplateResponse(
        "results.html", {"request": request, "source": source, **results.model_dump()})


@app.get("/get-query-history")
async def get_query_history(request: Request):
    """
    Query history route
    """
    session_id = request.cookies.get("session_id")
    return templates.TemplateResponse(
        "history.html",
        {"request": request, "queries": await app.state.db_client.get_session_queries(session_id)})


@app.get("/item")
async def item(doc_id: str, request: Request):
    item = await app.state.db_client.find_one(doc_id)
    return templates.TemplateResponse(
        "item.html", {"request": request, "item": item})


@app.get("/count")
async def index():
    """
    Unexposed route for document count
    """
    return {"message": {"Estimated document count": await app.state.db_client.count()}}


@app.post("/query")
async def query_route(query_params: QueryParams, limit: int=100, skip: int=0) -> List[DBEntryModel]:
    """
    API route for querying the database
    """
    query = build_query(**query_params.model_dump())
    logger.info(query)
    cursor = app.state.db_client.find(query, limit=limit, skip=skip)
    return await cursor.to_list(length=None)


@app.post("/upload-file")
async def upload(file: UploadFile = File(...), 
                 chunk: int = Form(...), 
                 total_chunks: int = Form(...),
                 file_id: str = Form(...),
                 background_tasks: BackgroundTasks=None):
    if chunk == 0:
        await app.state.db_client.register_upload(file_id, file.filename, Status.UPLOADING)
    app.state.file_upload.add_chunk(file_id, chunk, await file.read())
    if chunk == total_chunks - 1:
        background_tasks.add_task(app.state.file_upload.process_file, file_id)
    return


@app.get("/check-upload-status/{file_id}", response_model=FileUploadModel)
async def check_upload_status(file_id: str):
    status = await app.state.db_client.find_upload_status(file_id)
    if not status:
        raise HTTPException(status_code=404, detail="File not found")
    return status


@app.get("/get-upload-history", response_model=List[FileUploadModel])
async def get_upload_history():
    # if secret == settings.UPLOAD_SECRET:
    return await app.state.db_client.get_upload_history()
    # return []


@app.get("/get-upload-log")
async def get_upload_log(file_id: str):
    log_filename = utils.get_log_filename(file_id)
    filename = await app.state.db_client.get_upload_filename(file_id)
    if os.path.isfile(log_filename):
        async with aiofiles.open(log_filename, "rb") as f:
            return StreamingResponse(io.BytesIO(await f.read()),
                media_type='application/octet-stream',
                headers={"Content-Disposition": f"attachment; filename={filename}.log"})
    else:
        raise HTTPException(status_code=404, detail="File not found")


@app.get("/{}".format(settings.UPLOAD_SECRET), response_class=HTMLResponse)
async def upload_page(request: Request):
    """
    Upload route
    """
    return templates.TemplateResponse(
        "upload.html", 
        {"request": request,
         "statuses": Status.__get_classes__()})


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    # make sure db's are set and indexed

    # make sure folders exist
    if not os.path.isdir(settings.UPLOAD_LOG_DIR):
        os.makedirs(settings.UPLOAD_LOG_DIR)

    import uvicorn
    uvicorn.run("app:app",
                host='0.0.0.0',
                port=settings.PORT,
                workers=settings.WORKERS,
                reload=args.debug)

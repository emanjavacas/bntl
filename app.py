
import io
import os
import logging
from typing import List
import urllib.parse
from datetime import datetime, timezone
from contextlib import asynccontextmanager
import uuid
from bson.objectid import ObjectId
import humanize
import aiofiles
import rispy

from fastapi import FastAPI, Request, Depends, Response, status
from fastapi import UploadFile, File, BackgroundTasks, HTTPException, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from bntl.vector import VectorClient, MissingVectorException
from bntl.db import DBClient
from bntl.models import QueryParams, VectorParams, LoginParams, PageParams
from bntl.models import DBEntryModel, VectorEntryModel, FileUploadModel
from bntl.models import DocScreen
from bntl.pagination import paginate, paginate_within, build_query
from bntl.upload import Status, FileUploadManager, convert_to_text
from bntl.settings import settings, setup_logger
from bntl import utils

from vectorizer import client


setup_logger()
logger = logging.getLogger(__name__)


DESCRIPTION = """
## Introduction

Search engine + front end for a Zotero database
"""
VALIDATED_SESSIONS = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_client = await DBClient.create()
    app.state.vector_client = VectorClient()
    app.state.file_upload = FileUploadManager(
        app.state.db_client, 
        app.state.vector_client)
    yield
    app.state.db_client.close()
    await app.state.vector_client.close()


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
templates.env.filters["doc_repr"] = DocScreen.render_doc


@app.middleware("http")
async def add_session_id_cookie(request: Request, call_next):
    """
    This middleware adds a session id from the browser cookie, which will be
    eventually validated after a password check to ensure access to protected routes
    during the entire lifetime of the session cookie
    """
    session_id = request.cookies.get("session_id")
    if not session_id:
        session_id = str(uuid.uuid4())
    response = await call_next(request)
    response.set_cookie(key="session_id", value=session_id, httponly=True, samesite="Lax")
    return response


class RequiresLoginException(Exception):
    pass


@app.exception_handler(RequiresLoginException)
async def exception_handler(request: Request, e: RequiresLoginException) -> Response:
    return RedirectResponse(url=f"/login?next_url={e.args[0]['next_url']}")


def require_validated_session(request: Request):
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in VALIDATED_SESSIONS:
        raise RequiresLoginException({"next_url": request.url.path})


@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login_post(login_params: LoginParams, request: Request=None):
    if login_params.password == settings.UPLOAD_SECRET:
        session_id = request.cookies.get("session_id")
        if session_id:
            VALIDATED_SESSIONS.add(session_id)
            return JSONResponse({"status_code": status.HTTP_303_SEE_OTHER})
            # RedirectResponse(login_params.next_url, status_code=status.HTTP_303_SEE_OTHER)
        else:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown session")
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong password")


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


@app.get("/quickQuery")
async def quick_query(request: Request,
                      query_params: QueryParams=Depends(),
                      page_params: PageParams=Depends()):
    """
    Shortcut query route for the database without registering queries in the db.
    It is only meant to be used in quick-queries like links pointing to authors or keywords.
    """
    results = await paginate(app.state.db_client.bntl_coll, query_params, page_params, DBEntryModel)
    # add source
    source = "/quickQuery?" + urllib.parse.urlencode(dict(request.query_params))
    return templates.TemplateResponse(
        "results.html", {"request": request, "source": source, **results.model_dump()})


@app.get("/paginate")
async def paginate_route(query_id: str, request: Request, page_params: PageParams=Depends()):
    """
    Paginate route when moving forward and backward on a given query
    """
    session_id = request.cookies.get("session_id")
    query_data = await app.state.db_client.get_query(query_id, session_id)
    if not query_data:
        return JSONResponse(status_code=404, content={"error": "Query not found"})

    query_params = QueryParams.model_validate(query_data['query_params'])
    results = await paginate(app.state.db_client.bntl_coll, query_params, page_params, DBEntryModel)
    # store total on query database for preview & last accessed
    await app.state.db_client.update_query(
        query_id, session_id, 
        {"n_hits": results.n_hits, "last_accessed": datetime.now(timezone.utc)})

    return templates.TemplateResponse(
        "results.html",
        {"request": request, 
         "query_id": query_id, 
         "source": f"/paginate?query_id={query_id}", 
         **results.model_dump()})


@app.get("/paginate-within")
async def paginate_within_route(query_id: str, query_str: str, request: Request, page_params: PageParams=Depends()):
    """
    Paginate route for recursive queries
    """
    session_id = request.cookies.get("session_id")
    query_data = await app.state.db_client.get_query(query_id, session_id)
    if not query_data:
        return JSONResponse(status_code=404, content={"error": "Query not found"})

    query_params = QueryParams.model_validate(query_data['query_params'])
    results = await paginate_within(app.state.db_client.bntl_coll, query_params, query_str, page_params, DBEntryModel)

    source = f"/paginate-within?query_id={query_id}&query_str={query_str}"
    return templates.TemplateResponse(
        "results.html", {"request": request, "is_within": True, "source": source, **results.model_dump()})


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


@app.get("/vectorQuery")
async def vector_query(doc_id: str, request: Request, page_params: PageParams=Depends(), vector_params: VectorParams=Depends()):
    """
    Vector-based query route using the document id
    """
    try:
        hits = await app.state.vector_client.search(doc_id, limit=vector_params.limit)
    except MissingVectorException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Vector DB not running")

    hits_mapping = {item["doc_id"]: item["score"] for item in hits}

    def transform(item):
        item["score"] = hits_mapping[item["doc_id"]]
        return item

    # overwrite pagination, since we are not using it for now
    page_params.size = 100
    results = await paginate(
        app.state.db_client.bntl_coll, 
        {"_id": {"$in": [ObjectId(item["doc_id"]) for item in hits]}}, 
        page_params, VectorEntryModel, transform)

    # ensure we sort by score unless differently specified
    if not page_params.sort_author and not page_params.sort_year:
        results.items = sorted(results.items, key=lambda item: hits_mapping[item.doc_id], reverse=True)

    # add source
    source = "/vectorQuery?doc_id=" + doc_id
    return templates.TemplateResponse(
        "results.html", {"request": request, "source": source, **results.model_dump()})


@app.get("/count")
async def index():
    """
    Unexposed route for document count
    """
    return {"message": {"Estimated document count": await app.state.db_client.count()}}


@app.post("/upload-file", dependencies=[Depends(require_validated_session)])
async def upload(file: UploadFile = File(...), 
                 chunk: int = Form(...), 
                 total_chunks: int = Form(...),
                 file_id: str = Form(...),
                 background_tasks: BackgroundTasks=None):
    if chunk == 0:
        await app.state.db_client.register_upload(file_id, file.filename, Status.UPLOADING)
    app.state.file_upload.add_chunk(file_id, chunk, await file.read())
    if chunk == total_chunks - 1:
        background_tasks.add_task(app.state.file_upload.process_file_task, file_id)
    return


@app.get("/check-upload-status/{file_id}", response_model=FileUploadModel, dependencies=[Depends(require_validated_session)])
async def check_upload_status(file_id: str):
    status = await app.state.db_client.find_upload_status(file_id)
    if not status:
        raise HTTPException(status_code=404, detail="File not found")
    return status


@app.get("/get-upload-history", response_model=List[FileUploadModel], dependencies=[Depends(require_validated_session)])
async def get_upload_history():
    return await app.state.db_client.get_upload_history()


@app.get("/get-upload-log", dependencies=[Depends(require_validated_session)])
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


@app.get("/upload", response_class=HTMLResponse, dependencies=[Depends(require_validated_session)])
async def upload_page(request: Request):
    """
    Upload route
    """
    return templates.TemplateResponse(
        "upload.html", 
        {"request": request,
         "statuses": Status.__get_classes__()})


async def revectorize_task():
    task_id = "revectorize-" + str(uuid.uuid4())
    async with utils.AsyncLogger(task_id) as a_logger:
        await a_logger.info("Starting revectorize task: {}".format(task_id))
        docs = await app.state.db_client.find()
        doc_ids = [str(doc["_id"]) for doc in docs]
        texts = [convert_to_text(doc, ignore_keywords=True) for doc in docs],
        await a_logger.info("Revectorizing {} documents...".format(len(docs)))
        vectors = await client.vectorize(
            app.state.db_client.vectors_coll, task_id, texts, doc_ids, logger=a_logger)
        if vectors:
            await app.state.vector_client._clear_up()
            await a_logger.info("Indexing...")
            await app.state.vector_client.insert(vectors, doc_ids)
            await a_logger.info("Done indexing")
        else:
            await a_logger.info("Couldn't get vectors during reindex operation")


@app.post("/revectorize", dependencies=[Depends(require_validated_session)])
async def revectorize(background_tasks: BackgroundTasks):
    background_tasks.add_task(revectorize_task)
    return "Ok"


@app.get("/query-autocomplete")
async def query_autocomplete(field: str, query: str=Query(..., min_length=3)):
    return await app.state.db_client.find_autocomplete_by_prefix(field, query)


@app.get("/export-record")
async def export_record(doc_id: str, format: str):
    doc = await app.state.db_client.get_doc_source(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Unknown document: {doc_id}")

    if format == "ris":
        output = rispy.dumps([doc])
    elif format == "bib":
        output = await utils.ris2bib(rispy.dumps([doc]))
    else:
        raise HTTPException(status_code=404, detail=f"Unknown format: [{format}]")
    
    return StreamingResponse(io.BytesIO(output.encode()))


@app.get("/export-query")
async def export_query(query_id: str, format: str, request: Request):
    session_id = request.cookies.get("session_id")
    query_data = await app.state.db_client.get_query(query_id, session_id)
    if not query_data:
        return HTTPException(status_code=404, detail="Query not found")

    query_params = QueryParams.model_validate(query_data['query_params'])
    query = build_query(**query_params.model_dump())

    docs = await app.state.db_client.find(query, limit=settings.MAX_EXPORT_RESULTS)
    sources = await app.state.db_client.get_docs_source([doc['doc_id'] for doc in docs])

    if format == "ris":
        output = rispy.dumps(sources)
    elif format == "bib":
        output = await utils.ris2bib(rispy.dumps(sources))
    else:
        raise HTTPException(status_code=404, detail=f"Unknown format: [{format}]")
    return StreamingResponse(io.BytesIO(output.encode()))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    # make sure folders exist
    if not os.path.isdir(settings.UPLOAD_LOG_DIR):
        os.makedirs(settings.UPLOAD_LOG_DIR)

    import uvicorn
    uvicorn.run("app:app",
                host='0.0.0.0',
                port=settings.PORT,
                workers=settings.WORKERS,
                reload=args.debug)

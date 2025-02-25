
import io
import os
import random
import logging
import functools
from typing import List, Union, get_args
import urllib.parse
from datetime import datetime, timezone
from contextlib import asynccontextmanager

import humanize
import aiofiles
import rispy
import gettext
import redis.asyncio as redis

from fastapi import FastAPI, Request, Depends, Response, status
from fastapi import UploadFile, File, BackgroundTasks, HTTPException, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from bntl.vector_db import VectorClient, MissingVectorException
from bntl.vectorization import Status as VectorizationStatus, vectorize_task
from bntl.db import DBClient
from bntl.models import QueryParams, VectorParams, LoginParams, LoginMailParams, LoginCodeParams, PageParams
from bntl.models import DBDocumentModel, VectorEntryModel, FileUploadModel, VectorizationTaskModel
from bntl.models import get_record_screen_name, TypeOfReference
from bntl.pagination import paginate, paginate_within, build_query
from bntl.upload import Status as UploadStatus, FileUploadManager
from bntl.mail import send_verification_code
from bntl.settings import settings, setup_logger
from bntl import utils

setup_logger()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_client = await DBClient.create()
    app.state.vector_client = VectorClient()
    app.state.redis_client = redis.from_url(
            f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}", 
            decode_responses=True)
    app.state.file_upload = FileUploadManager(app.state.db_client)
    yield
    app.state.db_client.close()
    await app.state.vector_client.close()
    await app.state.redis_client.close()


app = FastAPI(
    title="BNTL", 
    description="Search engine + front end for a Zotero database",
    summary="BNTL database server application",
    version="0.0.0",
    lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"])

# declare templates
templates = Jinja2Templates(directory="static/templates")
templates.env.filters["naturaltime"] = humanize.naturaltime
templates.env.filters["doc_repr"] = get_record_screen_name
templates.env.filters["parse_doc_id"] = utils.parse_doc_id
templates.env.filters["get_ref_type"] = utils.get_ref_type
# mount static folder
app.mount("/static", StaticFiles(directory="static", html=True), name="static")


def get_translation(locale: str):
    """Retrieve the gettext translation object for a specific locale."""
    gettext.bindtextdomain("messages", settings.TRANSLATIONS_DIR)
    gettext.textdomain("messages")
    return gettext.translation("messages", localedir=settings.TRANSLATIONS_DIR, languages=[locale], fallback=True)


@app.middleware("http")
async def add_locale_middleware(request: Request, call_next):
    lang_param = request.query_params.get("lang", settings.DEFAULT_LOCALE)
    lang = get_translation(lang_param)
    lang.install()
    request.state._ = lang.gettext
    return await call_next(request)


@app.middleware("http")
async def add_session_id_cookie(request: Request, call_next):
    """
    This middleware adds a session id from the browser cookie, which will be
    eventually validated after a password check to ensure access to protected routes
    during the entire lifetime of the session cookie
    """
    session_id = request.cookies.get("session_id")
    if not session_id:
        session_id = utils.generate_id()
    response = await call_next(request)
    response.set_cookie(key="session_id", value=session_id, httponly=True, samesite="Lax")
    return response


def log_request(func):
    """
    A decorator to log the request parameters, headers, and additional arguments for specific routes.
    """
    @functools.wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        logger.info(
            f"Request: method={request.method}, url={request.url}, "
            f"headers={dict(request.headers)}, args={args}, kwargs={kwargs}")
        return await func(request, *args, **kwargs)
    return wrapper


# login logic
class RequiresLoginException(Exception):
    pass


@app.exception_handler(RequiresLoginException)
async def exception_handler(request: Request, e: RequiresLoginException) -> Response:
    """
    Redirect to login upon unauthorized request to required-login endpoint
    """
    return RedirectResponse(url=f"/login?next_url={e.args[0]['next_url']}")


async def require_validated_session(request: Request):
    """
    Dependency injection for protected routes
    """
    session_id = request.cookies.get("session_id")
    if not session_id or not await app.state.redis_client.exists(f"session:{session_id}"):
        raise RequiresLoginException({"next_url": request.url.path})


@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_get(request: Request, lang: str=Query(default=settings.DEFAULT_LOCALE)):
    return templates.TemplateResponse(
        "login.html" if settings.AUTH == "password" else "login_mail.html", 
        {"request": request, "_": get_translation(lang).gettext, "lang": lang})
    

async def handle_mail_login(session_id: str, mail: str, redis_client):
    if mail not in settings.ADMIN_MAILS:
        raise HTTPException(status_code=401, detail="Unauthorized email")
    
    code = str(random.randint(1000, 9999))
    await redis_client.delete(f"code:{session_id}")
    await redis_client.setex(f"code:{session_id}", settings.VERIFICATION_TOKEN_TIME, code)
    send_verification_code(mail, code)
    return JSONResponse({"next_step": "code"})


async def handle_code_verification(session_id: str, code: str, redis_client):
    stored_code = await redis_client.get(f"code:{session_id}")
    if not stored_code:
       raise HTTPException(status_code=404, detail="Couldn't fetch code for session")
    if code == stored_code:
        await redis_client.setex(f"session:{session_id}", settings.SESSION_TIME, "validated")
        return JSONResponse({"status_code": status.HTTP_303_SEE_OTHER})
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong code")


async def handle_password_login(session_id: str, password: str, redis_client):
    if password == settings.AUTH_SECRET:
        await redis_client.setex(f"session:{session_id}", settings.SESSION_TIME, "validated")
        return JSONResponse({"status_code": status.HTTP_303_SEE_OTHER})
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong password")


@app.post("/login", include_in_schema=False)
async def login_post(login_params: Union[LoginParams, LoginMailParams, LoginCodeParams], 
                     request: Request=None):
    if session_id := request.cookies.get("session_id"):
        # password-based
        if settings.AUTH == "password":
            return await handle_password_login(session_id, login_params.password, app.state.redis_client)
        # mail-based
        else:
            if hasattr(login_params, "mail"):
                return await handle_mail_login(session_id, login_params.mail, app.state.redis_client)
            if hasattr(login_params, "code"):
                return await handle_code_verification(session_id, login_params.code, app.state.redis_client)

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown session")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, lang: str=Query(default=settings.DEFAULT_LOCALE)):
    """
    Home route
    """
    return templates.TemplateResponse(
        "index.html", 
        {"request": request,
         "_": get_translation(lang).gettext, "lang": lang,
         "type_of_reference": get_args(TypeOfReference),
         "total_documents": await app.state.db_client.count(), 
         "last_added": await app.state.db_client.find_last_added()})


@app.get("/about", response_class=HTMLResponse)
async def about(request: Request, lang: str=Query(default=settings.DEFAULT_LOCALE)):
    """
    About route
    """
    return templates.TemplateResponse("about.html", {"request": request, "_": get_translation(lang).gettext, "lang": lang})


@app.get("/help", response_class=HTMLResponse)
async def help(request: Request, lang: str=Query(default=settings.DEFAULT_LOCALE)):
    """
    Help route showing information about the functioning of the app
    """
    return templates.TemplateResponse("help.html", {"request": request, "_": get_translation(lang).gettext, "lang": lang})


@app.post("/registerQuery")
@log_request
async def register_query(request: Request, query_params: QueryParams):
    """
    Log a query and store the parameters so that we can later show it in the query history
    """
    session_id = request.cookies.get("session_id")
    if query_data := await app.state.db_client.find_query(session_id, query_params):
        query_id = query_data["_id"]
    else:
        query_id = await app.state.db_client.register_query(session_id, query_params)
    return JSONResponse(content={"query_id": str(query_id)})


@app.get("/quickQuery")
@log_request
async def quick_query(request: Request, 
                      lang: str=Query(default=settings.DEFAULT_LOCALE),
                      query_params: QueryParams=Depends(),
                      page_params: PageParams=Depends()):
    """
    Shortcut query route for the database without registering queries in the db.
    It is only meant to be used in quick-queries like links pointing to authors or keywords.
    """
    results = await paginate(app.state.db_client.bntl_coll, query_params, page_params, DBDocumentModel)
    # add source
    source = "/quickQuery?" + urllib.parse.urlencode(dict(request.query_params))
    return templates.TemplateResponse(
        "results.html", {"request": request, 
                         "_": get_translation(lang).gettext, "lang": lang, 
                         "source": source, **results.model_dump()})


@app.get("/paginate")
@log_request
async def paginate_route(request: Request, 
                         query_id: str, 
                         lang: str=Query(default=settings.DEFAULT_LOCALE), 
                         page_params: PageParams=Depends()):
    """
    Paginate route when moving forward and backward on a given query
    """
    session_id = request.cookies.get("session_id")
    if query_data := await app.state.db_client.get_query(query_id, session_id):
        query_params = QueryParams.model_validate(query_data['query_params'])
        results = await paginate(app.state.db_client.bntl_coll, query_params, page_params, DBDocumentModel)
        # store total on query database for preview & last accessed
        await app.state.db_client.update_query(
            query_id, session_id, 
            {"n_hits": results.n_hits, "last_accessed": datetime.now(timezone.utc)})

        return templates.TemplateResponse(
            "results.html",
            {"request": request, 
            "_": get_translation(lang).gettext, "lang": lang,
            "query_id": query_id, 
            "source": f"/paginate?query_id={query_id}", 
            **results.model_dump()})

    return JSONResponse(status_code=404, content={"error": "Query not found"})


@app.get("/paginateWithin")
@log_request
async def paginate_within_route(request: Request,
                                query_id: str, 
                                query_str: str, 
                                lang: str=Query(default=settings.DEFAULT_LOCALE), 
                                page_params: PageParams=Depends()):
    """
    Paginate route for recursive queries
    """
    session_id = request.cookies.get("session_id")
    if query_data := await app.state.db_client.get_query(query_id, session_id):
        query_params = QueryParams.model_validate(query_data['query_params'])
        results = await paginate_within(app.state.db_client.bntl_coll, query_params, query_str, page_params, DBDocumentModel)

        source = f"/paginateWithin?query_id={query_id}&query_str={query_str}"
        return templates.TemplateResponse(
            "results.html", {"request": request, 
                            "_": get_translation(lang).gettext, "lang": lang, 
                            "is_within": True, 
                            "source": source, 
                            **results.model_dump()})

    return JSONResponse(status_code=404, content={"error": "Query not found"})


@app.get("/history")
async def query_history(request: Request, lang: str=Query(default=settings.DEFAULT_LOCALE)):
    """
    Query history route
    """
    session_id = request.cookies.get("session_id")
    return templates.TemplateResponse(
        "history.html",
        {"request": request, 
         "_": get_translation(lang).gettext, "lang": lang, 
         "queries": await app.state.db_client.get_session_queries(session_id)})


@app.get("/item")
async def item(doc_id: str, request: Request, lang: str=Query(default=settings.DEFAULT_LOCALE)):
    doc_id = utils.unparse_doc_id(doc_id)
    if item := await app.state.db_client.find_one(doc_id):
        return templates.TemplateResponse(
            "item.html", {"request": request, 
                          "_": get_translation(lang).gettext, "lang": lang, 
                          "item": item})
    raise HTTPException(status_code=404, detail=f"Unknown document: {doc_id}")


@app.get("/vectorQuery")
@log_request
async def vector_query(request: Request, 
                       doc_id: str, 
                       lang: str=Query(default=settings.DEFAULT_LOCALE),
                       page_params: PageParams=Depends(), 
                       vector_params: VectorParams=Depends()):
    """
    Vector-based query route using the document id
    """
    try:
        hits = await app.state.vector_client.search(
            utils.unparse_doc_id(doc_id), limit=vector_params.limit)
    except MissingVectorException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Vector DB not running")

    hits_mapping = {item["doc_id"]: item["score"] for item in hits}

    def transform(item):
        item["score"] = hits_mapping[item["document"]["id"]]
        return item

    # overwrite pagination, since we are not using it for now
    page_params.size = 100
    results = await paginate(
        app.state.db_client.bntl_coll,
        QueryParams(), page_params, VectorEntryModel, 
        within_ids=[item["doc_id"] for item in hits],
        transform=transform)

    # ensure we sort by score unless differently specified
    if not page_params.sort_author or not page_params.sort_year:
        results.items = sorted(
            results.items,
            key=lambda item: hits_mapping[item.document.id], reverse=True)

    # add source
    source = "/vectorQuery?doc_id=" + doc_id
    return templates.TemplateResponse(
        "results.html", {"request": request, 
                         "_": get_translation(lang).gettext, "lang": lang, 
                         "source": source, **results.model_dump()})


@app.get("/count")
async def index():
    """
    Unexposed route for document count
    """
    return {"message": {"Estimated document count": await app.state.db_client.count()}}


@app.get("/resetDatabase", dependencies=[Depends(require_validated_session)], include_in_schema=False)
async def reset_database():
    await app.state.db_client._clear_up()
    await app.state.vector_client._clear_up()
    return RedirectResponse(url="/")


# file upload
@app.get("/upload", response_class=HTMLResponse, dependencies=[Depends(require_validated_session)], include_in_schema=False)
async def upload_page(request: Request, lang: str=Query(default=settings.DEFAULT_LOCALE)):
    """
    Upload route
    """
    return templates.TemplateResponse(
        "upload.html", 
        {"request": request,
         "_": get_translation(lang).gettext, "lang": lang,
         "statuses": UploadStatus.__get_classes__()})


@app.post("/uploadFile", dependencies=[Depends(require_validated_session)])
async def upload(file: UploadFile = File(...), 
                 chunk: int = Form(...), 
                 total_chunks: int = Form(...),
                 file_id: str = Form(...),
                 background_tasks: BackgroundTasks=None):
    if chunk == 0:
        await app.state.db_client.register_upload(file_id, file.filename, UploadStatus.UPLOADING)
    app.state.file_upload.add_chunk(file_id, chunk, await file.read())
    if chunk == total_chunks - 1:
        background_tasks.add_task(app.state.file_upload.process_file_task, file_id)
    return


@app.get("/checkUploadStatus/{file_id}", response_model=FileUploadModel, dependencies=[Depends(require_validated_session)])
async def check_upload_status(file_id: str):
    status = await app.state.db_client.find_upload_status(file_id)
    if not status:
        raise HTTPException(status_code=404, detail="File not found")
    return status


@app.get("/getUploadHistory", response_model=List[FileUploadModel], dependencies=[Depends(require_validated_session)])
async def get_upload_history():
    return await app.state.db_client.get_upload_history()


@app.get("/getUploadLog", dependencies=[Depends(require_validated_session)])
async def get_upload_log(file_id: str):
    log_filename = utils.get_upload_log_filename(file_id)
    filename = await app.state.db_client.get_upload_filename(file_id)
    if os.path.isfile(log_filename):
        async with aiofiles.open(log_filename, "rb") as f:
            return StreamingResponse(io.BytesIO(await f.read()),
                media_type='application/octet-stream',
                headers={"Content-Disposition": f"attachment; filename={filename}.log"})
    else:
        raise HTTPException(status_code=404, detail="File not found")


# vectorization
@app.get("/vectorize", response_class=HTMLResponse, dependencies=[Depends(require_validated_session)], include_in_schema=False)
async def vectorize_page(request: Request, lang: str=Query(default=settings.DEFAULT_LOCALE)):
    """
    Vectorize route: vectorize full DB
    """
    return templates.TemplateResponse(
        "vectorize.html",
        {"request": request,
         "_": get_translation(lang).gettext, "lang": lang,
         "statuses": VectorizationStatus.__get_classes__()})


@app.post("/vectorize", dependencies=[Depends(require_validated_session)], include_in_schema=False)
async def vectorize(background_tasks: BackgroundTasks):
    if history := await app.state.db_client.get_vectorization_history():
        last_task = history[-1]
        last_status = last_task["current_status"]
        if not VectorizationStatus.is_done(last_status["status"]):
            raise HTTPException(status_code=409, detail="Service is busy, another task is running")
    task_id = utils.generate_id()
    await app.state.db_client.register_vectorization(task_id, VectorizationStatus.VECTORIZING)
    background_tasks.add_task(vectorize_task, app.state.db_client, app.state.vector_client, task_id)
    return {"status": "ok", "taskId": task_id}


@app.get("/checkVectorizationStatus/{task_id}", response_model=VectorizationTaskModel, dependencies=[Depends(require_validated_session)])
async def check_vectorization_status(task_id: str):
    status = await app.state.db_client.find_vectorization_status(task_id)
    if not status:
        raise HTTPException(status_code=404, detail="Task not found")
    return status


@app.get("/getVectorizationHistory", response_model=List[VectorizationTaskModel], dependencies=[Depends(require_validated_session)])
async def get_vectorization_history():
    return await app.state.db_client.get_vectorization_history()


@app.get("/getVectorizationLog", dependencies=[Depends(require_validated_session)], include_in_schema=False)
async def get_vectorization_log(task_id: str):
    log_filename = utils.get_vectorization_log_filename(task_id)
    if os.path.isfile(log_filename):
        async with aiofiles.open(log_filename, "rb") as f:
            return StreamingResponse(io.BytesIO(await f.read()),
                media_type='application/octet-stream',
                headers={"Content-Disposition": f"attachment; filename=vectorization_log_{task_id}.log"})
    else:
        raise HTTPException(status_code=404, detail="File not found")


# autocompletion
@app.get("/getCompletions", include_in_schema=False)
async def get_completions(field: str, query: str=Query(..., min_length=3)):
    return await app.state.db_client.find_autocomplete_by_prefix(field, query)


# export
def create_ris(*docs):
    def drop_none(doc):
        return {key: val for key, val in doc.items() if val is not None}
    return rispy.dumps([drop_none(doc) for doc in docs], mapping=utils.RISPY_MAPPING)


@app.get("/exportRis", response_class=PlainTextResponse, include_in_schema=False)
@log_request
async def export_ris(request: Request, doc_id: str):
    if doc := await app.state.db_client.find_one(doc_id):
        return create_ris(doc["document"])
    raise HTTPException(status_code=404, detail=f"Unknown document: {doc_id}")


@app.get("/exportQuery", include_in_schema=False)
@log_request
async def export_query(request: Request, query_id: str, format: str):
    session_id = request.cookies.get("session_id")
    query_data = await app.state.db_client.get_query(query_id, session_id)
    if not query_data:
        return HTTPException(status_code=404, detail="Query not found")

    query_params = QueryParams.model_validate(query_data['query_params'])
    query = build_query(**query_params.model_dump())

    docs = await app.state.db_client.find(query, limit=settings.MAX_EXPORT_RESULTS)
    docs = create_ris(*[doc["document"] for doc in docs])

    if format == "ris":
        output = docs
    elif format == "bib":
        output = await utils.ris2bib(docs)
    else:
        raise HTTPException(status_code=404, detail=f"Unknown format: [{format}]")
    return StreamingResponse(io.BytesIO(output.encode()))

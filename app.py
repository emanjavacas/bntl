
import logging
from typing import List
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from bson import ObjectId
import uuid
import humanize

from fastapi import FastAPI, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from bntl.db import BNTLClient, EntryModel, LocalClient
from bntl.queries import SearchQuery, build_query
from bntl.settings import settings, setup_logger
from bntl.pagination import paginate


setup_logger()
logger = logging.getLogger(__name__)


DESCRIPTION = """
## Introduction

Search engine + front end for a Zotero database
"""

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.bntl_client = BNTLClient()
    app.state.local_client = LocalClient()
    yield
    app.state.bntl_client.close()
    app.state.local_client.close()


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


@app.post("/registerQuery")
async def register_query(search_query: SearchQuery, request: Request):
    session_id = request.cookies.get("session_id")
    existing_query = app.state.local_client.query_coll.find_one(
        {"session_id": session_id, "search_query": search_query.dict()})
    if existing_query:
        query_id = existing_query["_id"]
    else:
        query_data = {}
        query_data["search_query"] = search_query.dict()
        query_data["session_id"] = session_id
        query_data["timestamp"] = datetime.now(timezone.utc)
        query_id = app.state.local_client.query_coll.insert_one(query_data).inserted_id
        logger.info("Registering query: %s", str(query_id))

    return JSONResponse(content={"query_id": str(query_id)})


@app.get("/paginate")
async def paginate_route(query_id: str, request: Request, page: int=Query(1, ge=1), size: int=Query(10, le=100)):
    session_id = request.cookies.get("session_id")
    query_data = app.state.local_client.query_coll.find_one({'_id': ObjectId(query_id), "session_id": session_id})
    logger.info(query_data)
    if not query_data:
        return JSONResponse(status_code=404, content={"error": "Query not found"})
    query_data.pop('_id')
    query = build_query(**query_data["search_query"])
    results = paginate(app.state.bntl_client.coll, query, EntryModel, page=page, size=size)
    # store total on query database for preview
    app.state.local_client.query_coll.update_one(
        {"session_id": session_id, "_id": ObjectId(query_id)},
        {"$set": {"n_hits": results.n_hits}})
    # store last accessed
    app.state.local_client.query_coll.update_one(
        {"session_id": session_id, "_id": ObjectId(query_id)},
        {"$set": {"last_accessed": datetime.now(timezone.utc)}})
    return templates.TemplateResponse(
        "results.html",
        {"request": request, "query_id": query_id, **results.dict()})


@app.get("/history")
async def history(request: Request):
    session_id = request.cookies.get("session_id")
    return templates.TemplateResponse(
        "history.html",
        {"request": request, "queries": app.state.local_client.get_session_queries(session_id)})


@app.get("/count")
async def index():
    return {"message": {"Estimated document count": len(app.state.bntl_client)}}


@app.post("/query")
async def query_route(search_query: SearchQuery, limit: int=100, skip: int=0) -> List[EntryModel]:
    query = build_query(**search_query.dict())
    logger.info(query)
    cursor = app.state.bntl_client.find(query, limit=limit, skip=skip)
    return list(cursor)


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
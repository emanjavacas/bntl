
import re
import json
from bson.objectid import ObjectId
import logging
import hashlib
from pydantic import ValidationError
from datetime import datetime, timezone
from typing import List, Optional, Union

import pymongo
from pymongo import InsertOne
import motor.motor_asyncio as motor

from bntl.settings import settings
from bntl import utils
from bntl.models import QueryModel, QueryParams, StatusModel
from bntl.models import DocumentModel, DBDocumentModel, ComputedFields

from vectorize.settings import settings as v_settings


logger = logging.getLogger(__name__)


class MissingFieldException(Exception):
    pass


class YearFormatException(Exception):
    pass


def parse_year(year):
    if year is None:
        return None
    try:
        return int(year)
    except Exception:
        if "x" in year.lower():
            year = year.lower().replace("x", "5")
            return parse_year(year)
        if "-" in year:
            m = re.match(r"([0-9]{4})-([0-9]{4})?", year)
            if not m:
                return year, None
            start, end = m.groups()
            return parse_year(start), parse_year(end)
    return None


def encode_year_range(year):
    """
    Utility function dealing with different input formats for the year field.
    We try to validate the year to a proper int and generate an end_year field to
    enable year range queries.
    """
    if year := parse_year(year):
        if isinstance(year, tuple):
            start, end = year
            return start, end
        return year, year + 1
    return None, None


def generate_document_hash(doc):
    """
    Generate document hash to avoid duplicates
    """
    doc_str = json.dumps(doc, sort_keys=True)
    return hashlib.sha256(doc_str.encode()).hexdigest()


def prepare_document(doc):
    """
    Adapt incoming document to internal database format and validate
    """
    start_year, end_year = encode_year_range(doc.get("year"))
    return DBDocumentModel(
        computed_fields=ComputedFields(start_year=start_year, end_year=end_year),
        date_added=datetime.now(timezone.utc),
        is_oa=bool(doc.get("urls")), # false if empty or None
        document=DocumentModel.model_validate(doc))


class DBClient():
    """
    Wrapper class for the MongoDB client.
    
    The application supports two types of search: faceted search (a.k.a advanced search)
    and full text search (shown in the index page). The latter uses a MongoDB text index
    over all string fields. The former uses a SaaS solution by MongoDB (alledgedly a Lucene
    integration).

    This client (as well as the pagination code) abstracts over the differences.

    Besides search, we use the MongoDB client to store information about the queries in order to:
    - show query history per user
    - optimize the communication between client and server during search
    """
    # this is a mapping from fields in the indexed documents to the fields in the query params
    AUTOCOMPLETE_TARGETS = {
        "keywords": "keywords", 
        "first_authors": "author", 
        "secondary_authors": "author", 
        "tertiary_authors": "author",
        "title": "title",
        "secondary_title": "title",
        "tertiary_title": "title"}

    def __init__ (self) -> None:
        uri = f"mongodb://{settings.MONGODB_HOST}:{settings.MONGODB_PORT}"
        logger.info("Starting DB client on: {}".format(uri))
        self.mongodb_client = motor.AsyncIOMotorClient(uri)
        self.bntl_coll = self.mongodb_client[settings.LOCAL_DB][settings.BNTL_COLL]
        self.autocomplete_coll = self.mongodb_client[settings.LOCAL_DB][settings.AUTOCOMPLETE_COLL]
        self.query_coll = self.mongodb_client[settings.LOCAL_DB][settings.QUERY_COLL]
        self.upload_coll = self.mongodb_client[settings.LOCAL_DB][settings.UPLOAD_COLL]
        self.vectorization_coll = self.mongodb_client[settings.LOCAL_DB][settings.VECTORIZATION_COLL]
        # vectorize database to retrieve vectors when done
        self.vectors_coll = self.mongodb_client[v_settings.VECTORIZER_DB][v_settings.VECTORS_COLL]

    @classmethod
    async def create(cls):
        self = cls()
        await self.ensure_indices()
        return self

    async def ensure_indices(self):
        # ensure unique index
        logger.info("Creating DB indices")
        await self.bntl_coll.create_index("document.id", unique=True)
        # ensure text search index
        await self.bntl_coll.create_index({"$**": "text"})
        await self.autocomplete_coll.create_index(("field", "value"), unique=True)
        await self.autocomplete_coll.create_index({"field": "text", "value": "text"})
        # ensure index on file_id (this may generate collisions)
        await self.upload_coll.create_index("file_id", unique=True)
    
    async def count(self):
        return await self.bntl_coll.estimated_document_count()

    async def ping(self):
        await self.mongodb_client.admin.command('ping')

    # document collection
    @staticmethod
    def collect_autocomplete(docs):
        """
        Collect all autocomplete information
        """
        autocomplete = set()
        for doc in docs:
            for target, field in DBClient.AUTOCOMPLETE_TARGETS.items():
                values: Union[List[str], str] = doc["document"].get(target, []) or [] # it may exist but have a None value
                values: List[str] = [values] if isinstance(values, str) else values # wrap
                autocomplete.update(set([(field, value) for value in values]))
        return [{"field": field, "value": value} for field, value in autocomplete]

    async def insert_documents(self, documents, logger=logger, progress_callback=None, callback_batch=500):
        doc_idx, done = -1, []

        for batch_id, start in enumerate(range(0, len(documents), callback_batch)):
            end, docs = start + callback_batch, []
            # collect documents
            for source_doc in documents[start: end]:
                doc_idx += 1
                doc_id = source_doc["id"]
                # validate
                try:
                    docs.append(prepare_document(dict(source_doc)).model_dump())
                except YearFormatException as e:
                    await utils.maybe_await(logger.info(
                        "Dropping document #{}:{} due to wrong year format".format(doc_idx, doc_id)))
                    await utils.maybe_await(logger.info(str(e)))
                except MissingFieldException as e:
                    await utils.maybe_await(logger.info(
                        "Dropping document #{}:{} due to missing field".format(doc_idx, doc_id)))
                    await utils.maybe_await(logger.info(str(e)))
                except ValidationError as e:
                    await utils.maybe_await(logger.info(
                        "Dropping document #{}:{} due to wrong data format".format(doc_idx, doc_id)))
                    await utils.maybe_await(logger.info(str(e)))

            errors = []
            try:
                # index documents
                await utils.maybe_await(logger.info("Batch-{}: Indexing {} documents".format(batch_id, len(docs))))
                if docs:
                    await self.bntl_coll.bulk_write([InsertOne(doc) for doc in docs], ordered=False)
            except pymongo.errors.BulkWriteError as e:
                errors = []
                for err in e.details['writeErrors']:
                    errors.append(err['index'])
                    if err['code'] == 11000:
                        await utils.maybe_await(logger.info("Dropping duplicate document #{}".format(start + err['index'])))
            except pymongo.errors.InvalidOperation as e:
                await utils.maybe_await(logger.info("No documents to index, exiting..."))
                return []

            finally:
                errors = set(errors)
                done.extend([doc["document"]["id"] for idx, doc in enumerate(docs) if idx not in errors])
                
                # index autocomplete data
                autocomplete = DBClient.collect_autocomplete(
                    [doc for idx, doc in enumerate(docs) if idx not in errors])
                try:
                    if autocomplete:
                        await utils.maybe_await(logger.info("Indexing {} autocomplete items".format(len(autocomplete))))
                        await self.autocomplete_coll.bulk_write([InsertOne(item) for item in autocomplete], ordered=False)
                except pymongo.errors.BulkWriteError as e:
                    await utils.maybe_await(logger.info("Got {}/{} errors while indexing autocomplete items".format(
                        len(e.details['writeErrors']), len(autocomplete))))

            if progress_callback is not None:
                await utils.maybe_await(progress_callback(doc_idx))

        return done

    async def find(self, query=None, limit=0, skip=0):
        cursor = self.bntl_coll.find(query or {}, limit=limit).skip(skip)
        results = await cursor.to_list(length=None)
        return results

    async def find_one(self, doc_id):
        return await self.bntl_coll.find_one({"document.id": doc_id})

    async def find_last_added(self, top=5):
        items, count = [], 0
        async for item in self.bntl_coll.find({}).sort("date_added", pymongo.DESCENDING):
            if count >= top:
                break
            items.append(item)
            count += 1
        return items

    # query collection
    async def get_session_queries(self, session_id) -> List[QueryModel]:
        """
        Retrieve the history of queries for a given user (a user is logged according to a session cookie).
        """
        cursor = self.query_coll.find({"session_id": session_id}).sort('data', pymongo.DESCENDING)
        return await cursor.to_list(length=None)

    async def get_query(self, query_id: str, session_id: str):
        return await self.query_coll.find_one({"_id": ObjectId(query_id), "session_id": session_id})

    async def find_query(self, session_id: str, query_params: Optional[QueryParams]=None):
        # validate existing query
        return await self.query_coll.find_one(
            {"session_id": session_id, "query_params": query_params.model_dump()})

    async def register_query(self, session_id: str, query_params: QueryParams):
        query_data = {}
        query_data["query_params"] = query_params.model_dump()
        query_data["session_id"] = session_id
        query_data["timestamp"] = datetime.now(timezone.utc)
        query_id = (await self.query_coll.insert_one(query_data)).inserted_id
        return query_id

    async def update_query(self, query_id: str, session_id: str, data):
        return await self.query_coll.update_one(
            {"session_id": session_id, "_id": ObjectId(query_id)},
            {"$set": data})
    
    # upload documents
    async def register_upload(self, file_id: str, filename: str, status: str):
        logger.info("Registering file {} with id [{}]".format(filename, file_id))
        return await self.upload_coll.insert_one(
            {"file_id": file_id, 
             "filename": filename,
             "date_uploaded": datetime.now(timezone.utc),
             "current_status": {"status": status, "date_updated": datetime.now(timezone.utc)},    
             "history": []})
    
    async def get_upload_history(self):
        cursor = self.upload_coll.find().sort("date_uploaded", pymongo.ASCENDING)
        return await cursor.to_list(length=None)

    async def update_upload_status(self, file_id: str, new_status: StatusModel):
        old_status = (await self.upload_coll.find_one({"file_id": file_id}))["current_status"]
        return await self.upload_coll.update_one(
            {"file_id": file_id},
            {"$set": {"current_status": new_status.model_dump()},
                "$push": {"history": old_status}},
            upsert=True)
    
    async def get_upload_filename(self, file_id: str):
        return (await self.upload_coll.find_one({"file_id": file_id}))["filename"]
    
    async def find_upload_status(self, file_id):
        return await self.upload_coll.find_one({"file_id": file_id})
    
    # vectorize database
    async def register_vectorization(self, task_id: str, status: str):
        return await self.vectorization_coll.insert_one(
            {"task_id": task_id, 
             "date_started": datetime.now(timezone.utc),
             "current_status": {"status": status, "date_updated": datetime.now(timezone.utc)},    
             "history": []})

    async def get_vectorization_history(self):
        cursor = self.vectorization_coll.find().sort("date_started", pymongo.ASCENDING)
        return await cursor.to_list(length=None)

    async def update_vectorization_status(self, task_id: str, new_status: StatusModel):
        old_status = (await self.vectorization_coll.find_one({"task_id": task_id}))["current_status"]
        return await self.vectorization_coll.update_one(
            {"task_id": task_id},
            {"$set": {"current_status": new_status.model_dump()},
                "$push": {"history": old_status}},
            upsert=True)

    async def find_vectorization_status(self, task_id):
        return await self.vectorization_coll.find_one({"task_id": task_id})

    # keywords
    async def find_autocomplete_by_prefix(self, field: str, prefix: str, limit=10) -> List[str]:
        output = await self.autocomplete_coll.find(
            {"field": field, "value": {"$regex": "^" + prefix + ".*", "$options": "i"}}, limit=limit
        ).to_list(length=None)
        return [item["value"] for item in output]

    def close(self):
        self.mongodb_client.close()

    async def _clear_up(self): # DANGER
        await self.bntl_coll.drop()
        await self.autocomplete_coll.drop()
        await self.query_coll.drop()
        await self.upload_coll.drop()
        await self.vectorization_coll.drop()
        # ensure we recreate the indices
        await self.ensure_indices()

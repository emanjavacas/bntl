
import re
import json
import bson
import logging
import hashlib
from pydantic import ValidationError
from datetime import datetime, timezone
from typing import List, Optional, Dict

import pymongo
import motor.motor_asyncio as motor

from bntl.settings import settings
from bntl import utils
from bntl.models import QueryModel, QueryParams, StatusModel, EntryModel

from vectorizer.settings import settings as v_settings


logger = logging.getLogger(__name__)


class MissingFieldException(Exception):
    pass


class YearFormatException(Exception):
    pass


def fix_year(doc):
    """
    Utility function dealing with different input formats for the year field.
    We try to validate the year to a proper int and add a end_year field to
    enable year range queries. If unable to do so, the document will be ingested,
    but wont be retrieved upon year queries. It's the curator's responsability
    to make sure the documents are in appropriate format.
    """
    try:
        doc['year'] = int(doc['year'])
        doc['end_year'] = doc['year'] + 1 # year is uninclusive
        return doc
    except Exception:
        # missing year
        if "year" not in doc:
            return doc
        # undefined years (eg. 197X), go for average value
        if 'X' in doc['year']:
            doc['year'] = doc['year'].replace('X', '5')
            return fix_year(doc)
        # range years (eg. 1987-2024, 1987-, ...)
        if '-' in doc['year']:
            m = re.match(r"([0-9]{4})-([0-9]{4})?", doc['year'])
            if not m:
                return doc
            start, end = m.groups()
            doc['year'] = int(start)
            doc['end_year'] = end or int(start) + 1 # use starting date if end year is missing

    return doc


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
    # fix year
    doc = fix_year(doc)
    doc = EntryModel.model_validate(doc).model_dump()
    # hash document
    doc["hash"] = generate_document_hash(doc)
    # add date
    doc["date_added"] = datetime.now(timezone.utc)
    return doc


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
    def __init__ (self) -> None:
        self.mongodb_client = motor.AsyncIOMotorClient(settings.LOCAL_URI)
        self.bntl_coll = self.mongodb_client[settings.LOCAL_DB][settings.BNTL_COLL]
        self.source_coll = self.mongodb_client[settings.LOCAL_DB][settings.SOURCE_COLL]
        self.keywords_coll = self.mongodb_client[settings.BNTL_DB][settings.KEYWORDS_COLL]
        self.query_coll = self.mongodb_client[settings.LOCAL_DB][settings.QUERY_COLL]
        self.upload_coll = self.mongodb_client[settings.LOCAL_DB][settings.UPLOAD_COLL]
        # vectorize database to retrieve vectors when done
        self.vectors_coll = self.mongodb_client[v_settings.VECTORIZER_DB][v_settings.VECTORS_COLL]

    @classmethod
    async def create(cls):
        self = cls()
        self.unique_refs = await self.bntl_coll.distinct("type_of_reference")
        await self.ensure_indices()
        return self

    async def ensure_indices(self):
        # ensure unique index
        logger.info("Creating DB indices")
        await self.bntl_coll.create_index("hash", unique=True)
        await self.source_coll.create_index("doc_id", unique=True)
        # ensure text search index
        await self.bntl_coll.create_index({"$**": "text"})
        await self.keywords_coll.create_index({"keyword": "text"}, unique=True)
        # ensure index on file_id (this may generate collisions)
        await self.upload_coll.create_index("file_id", unique=True)
    
    async def count(self):
        return await self.bntl_coll.estimated_document_count()

    async def ping(self):
        await self.mongodb_client.admin.command('ping')

    # document collection
    async def insert_documents(self, documents, logger=logger, progress_callback=None, callback_batch=500):
        done, keywords = [], []
        for doc_idx, source_doc in enumerate(documents):
            try:
                doc = prepare_document(source_doc)
                doc_id = (await self.bntl_coll.insert_one(doc)).inserted_id
                await self.source_coll.insert_one({"doc_id": str(doc_id), "source": source_doc})
                keywords.extend(doc.get('keywords', []) or [])
                done.append(str(doc_id))
            except YearFormatException as e:
                await utils.maybe_await(logger.info("Dropping document #{} due to wrong year format".format(doc_idx)))
                await utils.maybe_await(logger.info(str(e)))
            except MissingFieldException as e:
                await utils.maybe_await(logger.info("Dropping document #{} due to missing field".format(doc_idx)))
                await utils.maybe_await(logger.info(str(e)))
            except ValidationError as e:
                await utils.maybe_await(logger.info("Dropping document #{} due to wrong data format".format(doc_idx)))
                await utils.maybe_await(logger.info(str(e)))
            except pymongo.errors.DuplicateKeyError as e:
                await utils.maybe_await(logger.info("Dropping document #{} due to duplicate".format(doc_idx)))
                await utils.maybe_await(logger.info(str(e)))

            if progress_callback is not None and doc_idx > 0 and doc_idx % callback_batch == 0:
                await utils.maybe_await(progress_callback(doc_idx))

        try:
            await utils.maybe_await(logger.info("Indexing {} keywords...".format(len(keywords))))
            result = await self.keywords_coll.insert_many(
                [{"keyword": keyword} for keyword in set(keywords) if keyword],
                ordered=False)
            await utils.maybe_await(logger.info("Indexed {} new keywords".format(len(result))))
        except pymongo.errors.BulkWriteError as e:
            dups = len([e for e in e.details['writeErrors'] if e['code'] == 11000])
            new = e.details['nInserted']
            await utils.maybe_await(logger.info("Indexed {} new and rejected {} dup keywords".format(new, dups)))

        return done

    async def find(self, query=None, limit=0, skip=0):
        cursor = self.bntl_coll.find(query or {}, limit=limit).skip(skip)
        results = await cursor.to_list(length=None)
        for item in results:
            item['doc_id'] = str(item.pop("_id"))
        return results
    
    async def find_one(self, doc_id):
        item = await self.bntl_coll.find_one({"_id": bson.objectid.ObjectId(doc_id)})
        if item:
            item["doc_id"] = str(item.pop("_id"))
        return item

    async def find_last_added(self, top=3):
        items = []
        count = 0
        async for item in self.bntl_coll.find({}).sort("date_added", pymongo.DESCENDING):
            if count >= top:
                break
            item["doc_id"] = str(item.pop("_id"))
            items.append(item)
            count += 1
        return items
    
    async def get_doc_source(self, doc_id: str) -> Dict:
        doc = await self.source_coll.find_one({"doc_id": doc_id})
        return doc["source"]

    async def get_docs_source(self, doc_ids: List[str]) -> List[Dict]:
        docs = await self.source_coll.find({"doc_id": {"$in": doc_ids}}).to_list(length=None)
        return [doc["source"] for doc in docs]

    # query collection
    async def get_session_queries(self, session_id) -> List[QueryModel]:
        """
        Retrieve the history of queries for a given user (a user is logged according to a session cookie).
        """
        cursor = self.query_coll.find({"session_id": session_id}).sort('data', pymongo.DESCENDING)
        return await cursor.to_list(length=None)

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
            {"session_id": session_id, "_id": bson.objectid.ObjectId(query_id)},
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

    # keywords
    async def find_keywords_by_prefix(self, prefix:str, limit=10) -> List[str]:
        keywords = await self.keywords_coll.find(
            {"keyword": {"$regex": "^" + prefix + ".*", "$options": "i"}}, limit=limit
        ).to_list(length=None)
        return [item["keyword"] for item in keywords]

    def close(self):
        self.mongodb_client.close()

    async def _clear_up(self): # DANGER
        await self.bntl_coll.drop()
        await self.keywords_coll.drop()
        await self.query_coll.drop()
        await self.upload_coll.drop()
        await self.source_coll.drop()
        # ensure we recreate the indices
        await self.ensure_indices()




# if __name__ == '__main__':
#     import rispy
#     import argparse
#     parser = argparse.ArgumentParser()
#     parser.add_argument('--ris-file', required=True, help="Path to ris file with data to be indexed.")
#     args = parser.parse_args()

#     with open(args.ris_file, 'r') as f:
#         db = rispy.load(f)

#     _errors = []
#     for idx, item in enumerate(db):
#         try:
#             EntryModel.model_validate(item).dict()
#         except Exception:
#             _errors.append(idx)

    # from elasticsearch import Elasticsearch
    # from elasticsearch.helpers import bulk

    # username = 'elastic'
    # # password = os.getenv('ELASTIC_PASSWORD') # Value you set in the environment variable

    # client = Elasticsearch(
    #     "http://localhost:9200",
    #     basic_auth=(username, "elastic")
    # )

    # print(client.info())
    # mappings = {"properties": {"title": {"type": "text", "analyzer": "standard"},
    #                         "secondary_title": {"type": "text", "analyzer": "standard"},
    #                         "tertiary_title": {"type": "text", "analyzer": "standard"},
    #                         "authors": {"type": "text", "analyzer": "standard"},
    #                         "first_authors": {"type": "text", "analyzer": "standard"},
    #                         "secondary_authors": {"type": "text", "analyzer": "standard"},
    #                         "tertiary_authors": {"type": "text", "analyzer": "standard"},
    #                         "keywords": {"type": "text", "analyzer": "standard"}}}
    # client.indices.create(index="bntl", mappings=mappings)
    # docs = list(db_client.bntl_coll.find())
    # # client.indices.delete(index="bntl")
    # bulk(client,
    #     [{"_id": str(doc["_id"]), 
    #     "_index": "bntl", 
    #     "_source": {key: val for key, val in doc.items() if key != "_id"}} for doc in docs])
    # # client.cat.count(index="bntl", format="json")

    # res = client.search(
    #     index="bntl", 
    #     query={"multi_match": {"query": "kestemont", 
    #                         "fields": ["authors", "first_authors", "secondary_authors", "tertiary_authors",
    #                                     "title", ""],
    #                         "fuzziness": 2}})

    # local = LocalClient()
    # local.mongodb_client["bntl"]["bntl"].insert_many(docs)
    # create text index
    # local.mongodb_client["bntl"]["bntl"].create_index({"$**": "text"})

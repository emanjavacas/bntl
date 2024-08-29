
import bson
from datetime import datetime, timezone
import logging
from typing import List, Union, Optional

import bson.objectid
import pymongo
import motor.motor_asyncio as motor

from bntl.settings import settings
from bntl import utils
from bntl.models import QueryModel, SearchQuery


logger = logging.getLogger(__name__)


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
        self.mongodb_client1 = motor.AsyncIOMotorClient(settings.BNTL_URI)
        self.bntl_coll = self.mongodb_client1[settings.BNTL_DB][settings.BNTL_COLL]
        self.mongodb_client2 = motor.AsyncIOMotorClient(settings.LOCAL_URI)
        self.query_coll = self.mongodb_client2[settings.LOCAL_DB][settings.QUERY_COLL]
        self.upload_coll = self.mongodb_client2[settings.LOCAL_DB][settings.UPLOAD_COLL]

    @classmethod
    async def create(cls):
        self = cls()
        self.is_atlas = utils.is_atlas(settings.BNTL_URI)
        self.unique_refs = await self.bntl_coll.distinct("type_of_reference")
        return self

    async def ping(self):
        await self.mongodb_client1.admin.command('ping')
        await self.mongodb_client2.admin.command('ping')

    async def get_session_queries(self, session_id) -> List[QueryModel]:
        """
        Retrieve the history of queries for a given user (a user is logged according to a session cookie).
        """
        cursor = self.query_coll.find({"session_id": session_id}).sort('data', pymongo.DESCENDING)
        return await cursor.to_list(length=None)

    async def find(self, query=None, limit=100, skip=0):
        cursor = self.bntl_coll.find(query or {}, limit=limit).skip(skip)
        return await cursor.to_list(length=None)
    
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

    async def full_text_search(self, string, fuzzy=False, **fuzzy_kwargs):
        if not self.is_atlas:
            raise ValueError("full_text_search requires Atlas deployment")
        
        query = {"query": string, "path": {"wildcard": "*"}}
        if fuzzy: query["fuzzy"] = fuzzy_kwargs

        return await self.bntl_coll.aggregate([{"$search": {"index": "default", "text": query}}])

    async def get_query(self, query_id: str, session_id: str):
        return await self.query_coll.find_one(
            {'_id': bson.objectid.ObjectId(query_id), "session_id": session_id})

    async def find_query(self, session_id: str, search_query: Optional[SearchQuery]=None):
        # validate existing query
        return await self.query_coll.find_one(
            {"session_id": session_id, "search_query": search_query.model_dump()})

    async def register_query(self, session_id: str, search_query: SearchQuery):
        query_data = {}
        query_data["search_query"] = search_query.model_dump()
        query_data["session_id"] = session_id
        query_data["timestamp"] = datetime.now(timezone.utc)
        query_id = await self.query_coll.insert_one(query_data).inserted_id
        return query_id

    async def update_query(self, query_id: str, session_id: str, data):
        await self.query_coll.update_one(
            {"session_id": session_id, "_id": bson.objectid.ObjectId(query_id)},
            {"$set": data})

    async def update_upload_status(self, file_id: str, new_status: str):
        await self.update_coll.update_one(
            {"file_id": file_id},
            {"$set": {"current_status": new_status},
             "$push": {"status_history": {"status": new_status, "timestamp": datetime.now(timezone.utc)}}})

    def close(self):
        self.mongodb_client1.close()
        self.mongodb_client2.close()


def create_text_index(client: Union[DBClient]):
    """
    Create a text index for the local database for full-text search (see bntl.paginate)
    """
    if client.is_atlas:
        return
    client.bntl_coll.create_index({"$**": "text"})


def build_query(type_of_reference=None,
                title=None,
                year=None,
                author=None,
                keywords=None,
                use_regex_title=False,
                use_case_title=False,
                use_regex_author=False,
                use_case_author=False,
                use_regex_keywords=False,
                use_case_keywords=False,
                full_text=None):
    
    """
    Transform an incoming query into a MongoDB-ready query
    """

    if full_text: # shortcut
        return {"full_text": full_text}

    query = []

    if type_of_reference is not None:
        query.append({"type_of_reference": type_of_reference})

    if title is not None:
        if use_regex_title:
            title = {"$regex": title}
            if not use_case_title:
                title["$options"] = "i"
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
            query.append({"$and": [{"year": {"$gte": int(year)}},
                                   {"end_year": {"$lte": int(year) + 1}}]})

    if author is not None:
        if use_regex_author:
            author = {"$regex": author}
            if not use_case_author:
                author["$options"] = "i"
        query.append({"$or": [{"authors": author},
                              {"first_authors": author},
                              {"secondary_authors": author},
                              {"tertiary_authors": author}]})

    if keywords is not None:
        if use_regex_keywords:
            keywords = {"$regex": keywords}
            if not use_case_keywords:
                keywords["$options"] = "i"
        query.append({"keywords": keywords})

    if len(query) > 1:
        query = {"$and": query}
    elif len(query) == 1:
        query = query[0]
    else:
        query = {}

    return query



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
    # docs = list(bntl_client.bntl_coll.find())
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

import logging
import traceback

from typing import List, Union

from pydantic import ValidationError

import pymongo
from pymongo import MongoClient, errors

from bntl.settings import settings
from bntl import utils
from bntl.models import QueryModel, EntryModel


logger = logging.getLogger(__name__)


class BNTLClient():
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
        self.mongodb_client1 = MongoClient(settings.BNTL_URI)
        self.bntl_coll = self.mongodb_client1[settings.BNTL_DB][settings.BNTL_COLL]
        self.mongodb_client2 = MongoClient(settings.LOCAL_URI)
        self.query_coll = self.mongodb_client2[settings.LOCAL_DB][settings.QUERY_COLL]

        self.is_atlas = utils.is_atlas(settings.BNTL_URI)
        self.unique_refs = self.bntl_coll.distinct("type_of_reference")

    def __len__(self):
        return self.bntl_coll.estimated_document_count()

    def ping(self):
        self.mongodb_client1.admin.command('ping')
        self.mongodb_client2.admin.command('ping')

    def get_session_queries(self, session_id) -> List[QueryModel]:
        """
        Retrieve the history of queries for a given user (a user is logged according to a session cookie).
        """
        return list(self.query_coll.find({"session_id": session_id}).sort('data', pymongo.DESCENDING))

    def find(self, query=None, limit=100, skip=0):
        cursor = self.bntl_coll.find(query or {}, limit=limit).skip(skip)
        return cursor
    
    def full_text_search(self, string, fuzzy=False, **fuzzy_kwargs):
        if not self.is_atlas:
            raise ValueError("full_text_search requires Atlas deployment")
        
        query = {"query": string, "path": {"wildcard": "*"}}
        if fuzzy:
            query["fuzzy"] = fuzzy_kwargs
        cursor = self.bntl_coll.aggregate([
            {"$search": {"index": "default", "text": query}}])
        return cursor

    def close(self):
        self.mongodb_client1.close()
        self.mongodb_client2.close()


def insert_documents(collection, documents, batch_size=10_000):
    """
    General document ingestion logic
    """
    # TODO: offer a service for full ingestions that also register embeddings and updates the vector database

    doc_id = 0
    for start in range(0, len(documents), batch_size):
        end = min(start + batch_size, len(documents))
        logger.info("Inserting batch number {}: {}-to-{}".format(1 + (start // batch_size), start + 1, end))
        # validation
        subset = []
        for doc in documents[start:end]:
            try:
                doc = utils.fix_year(doc)
                doc = EntryModel.model_validate(doc).model_dump()
                subset.append(doc)
            except utils.YearFormatException:
                logger.info("Dropping document due to wrong year format, doc: {}".format(doc_id))
                logger.info(traceback.format_exc())
            except ValidationError:
                logger.info("Dropping document due to wrong format, doc: {}".format(doc_id))
                logger.info(traceback.format_exc())
            doc_id += 1
        # entry
        try:
            collection.insert_many(subset)
        except errors.BulkWriteError as e:
            panic = list(filter(lambda x: x['code'] != 11000, e.details['writeErrors']))
            for doc in panic:
                logger.info("Insert error for doc: {}".format(doc))


def create_text_index(client: Union[BNTLClient]):
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



if __name__ == '__main__':
    import rispy
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--ris-file', required=True, help="Path to ris file with data to be indexed.")
    args = parser.parse_args()

    with open(args.ris_file, 'r') as f:
        db = rispy.load(f)

    _errors = []
    for idx, item in enumerate(db):
        try:
            EntryModel.model_validate(item).dict()
        except Exception:
            _errors.append(idx)

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
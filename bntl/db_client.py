
import re
import bson
import logging
import traceback
from typing import List, Optional, Dict

from pydantic import BaseModel, Field, ConfigDict, ValidationError
from pymongo import MongoClient, errors

from bntl.settings import settings


logger = logging.getLogger(__name__)


class EntryModel(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    # mandatory
    label: str = Field(help="Zotero export validation result")
    name_of_database: str = Field(help="BNTL metadata")
    title: str = Field(help="Title of the record")
    type_of_reference: str = Field(help="Record format")
    year: int = Field(help="Year of record publication in string format")
    end_year: int = Field(help="Custom-made field to deal with range years (e.g. 1987-2024)")
    # optional
    secondary_title: Optional[str] = Field(default=None)
    tertiary_title: Optional[str] = Field(default=None)
    authors: Optional[List[str]] = Field(default=None)
    first_authors: Optional[List[str]] = Field(default=None)
    secondary_authors: Optional[List[str]] = Field(default=None)
    tertiary_authors: Optional[List[str]] = Field(default=None)
    journal_name: Optional[str] = Field(default=None)
    end_page: Optional[str] = Field(default=None)
    start_page: Optional[str] = Field(default=None)
    volume: Optional[str] = Field(default=None)
    number: Optional[str] = Field(default=None)
    edition: Optional[str] = Field(default=None)
    issn: Optional[str] = Field(default=None)
    publisher: Optional[str] = Field(default=None)
    place_published: Optional[str] = Field(default=None)
    urls: Optional[List[str]] = Field(default=None)
    note: Optional[str] = Field(default=None)
    research_notes: Optional[str] = Field(default=None)
    keywords: Optional[List[str]] = Field(default=None)
    unknown_tag: Optional[Dict[str, List[str]]] = Field(default=None)


class DBEntryModel(EntryModel):
    id: bson.objectid.ObjectId = Field(help='Internal MongoDB id', alias="_id")


class YearFormatException(Exception):
    pass


def fix_year(doc):
    """
    Utility function dealing with different input formats for the year field.
    """
    try:
        int(doc['year'])
        doc['end_year'] = int(doc['year']) + 1 # year is uninclusive
        return doc
    except:
        # undefined years (eg. 197X), go for average value
        if 'X' in doc['year']:
            doc['year'] = doc['year'].replace('X', '5')
        # range years (eg. 1987-2024, 1987-, ...)
        if '-' in doc['year']:
            m = re.match(r"([0-9]{4})-([0-9]{4})?", doc['year'])
            if not m: # error, skip the record
                raise YearFormatException(doc['year'])
            start, end = m.groups()
            doc['year'] = start
            doc['end_year'] = end or int(start) + 1 # use starting date if end year is missing

    return doc


class AtlasClient():
    def __init__ (self):
       self.mongodb_client = MongoClient(settings.MONGODB_URI)
       self.database = self.mongodb_client[settings.MONGODB_DB]
       self.bntl_coll = self.database[settings.MONGODB_BNTL_COLL]
       self.UNIQUE_REFS = unique_refs = self.bntl_coll.distinct("type_of_reference")

    def __len__(self):
        return self.bntl_coll.estimated_document_count()

    def ping(self):
       self.mongodb_client.admin.command('ping')

    def insert_documents(self, documents, batch_size=10_000):
        doc_id = 0
        for start in range(0, len(documents), batch_size):
            end = min(start + batch_size, len(documents))
            logger.info("Inserting batch number {}: {}-to-{}".format(1 + (start // batch_size), start + 1, end))
            # validation
            subset = []
            for doc in documents[start:end]:
                try:
                    doc = fix_year(doc)
                    doc = EntryModel.model_validate(doc).dict()
                    subset.append(doc)
                except YearFormatException:
                    logger.info("Dropping document due to wrong year format", doc_id)
                    logger.info(traceback.format_exc())
                except ValidationError:
                    logger.info("Dropping document due to wrong format", doc_id)
                    logger.info(traceback.format_exc())
                doc_id += 1
            # entry
            try:
                self.bntl_coll.insert_many(subset)
            except errors.BulkWriteError as e:
                panic = list(filter(lambda x: x['code'] != 11000, e.details['writeErrors']))
                for doc in panic:
                    logger.info("Insert error for document:", doc)

    def find(self, query=None, limit=100, skip=0):
       cursor = self.bntl_coll.find(query or {}, limit=limit).skip(skip)
       return cursor
    
    def close(self):
        self.mongodb_client.close()


if __name__ == '__main__':
    import rispy
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--ris-file', required=True, help="Path to ris file with data to be indexed.")
    args = parser.parse_args()
    
    # with open('merged.ris', 'r') as f:
    with open(args.ris_file, 'r') as f:
        db = rispy.load(f)
    
    client = AtlasClient()
    items = list(client.find(limit=1000000))


    client.insert_documents(db, batch_size=5_000)

    _errors = []
    for i in range(len(db)):
        try:
            EntryModel.model_validate(db[i]).dict()
        except:
            _errors.append(i)

    [db[errors[i]]['year'] for i in range(len(errors))]
    db[_errors[0]]

    cursor = client.bntl_coll.find({"$and": [{"secondary_title": "Flämische Schriften"}, 
                                             {"$and": [{"year": {"$gt": 1941}},
                                                       {"year": {"$lt": 1943}}]}]})
    
    list(cursor)
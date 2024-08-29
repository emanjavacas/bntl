
import rispy
import tqdm
import logging
import traceback
from datetime import datetime, timezone

from pydantic import ValidationError
from pymongo import errors

from bntl.db import BNTLClient, create_text_index
from bntl.vector import VectorClient
from bntl.models import EntryModel
from bntl import utils


logger = logging.getLogger(__name__)


def get_doc_text(doc):
    title = doc["title"] # seems mandatory
    if doc.get("secondary_title"):
        title += "; " + doc["secondary_title"]
    keywords = None
    if doc.get("keywords"):
        keywords = "; ".join(doc["keywords"])

    return {"title": title, "keywords": keywords}


def convert_to_text(doc, ignore_keywords=False):
    output = doc["title"]
    if doc["keywords"] and not ignore_keywords:
        output += "; " + doc["keywords"]
    return output


def validate(doc):
    if not doc["title"]:
        raise utils.MissingFieldException({"field": "title"})


def insert_documents(collection, documents, batch_size=10_000):
    """
    General document ingestion logic
    """
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
                doc["date_added"] = datetime.now(timezone.utc)
                validate(doc)
                subset.append(doc)
            except utils.YearFormatException:
                logger.info("Dropping document due to wrong year format, doc: {}".format(doc_id))
                logger.info(traceback.format_exc())
            except ValidationError:
                logger.info("Dropping document due to wrong format, doc: {}".format(doc_id))
                logger.info(traceback.format_exc())
            except utils.MissingFieldException:
                logger.info("Dropping document due to missing field, doc: {}".format(doc_id))
                logger.info(traceback.format_exc())
            doc_id += 1
        # entry
        try:
            collection.insert_many(subset)
        except errors.BulkWriteError as e:
            panic = list(filter(lambda x: x['code'] != 11000, e.details['writeErrors']))
            for doc in panic:
                logger.info("Insert error for doc: {}".format(doc))



if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--ris-file', required=True, help="Path to ris file with data to be indexed.")
    args = parser.parse_args()

    from bntl.settings import setup_logger
    setup_logger()

    vector_client = VectorClient()
    bntl_client = BNTLClient()

    with open(args.ris_file, 'r') as f:
        logger.info("Loading data from file")
        data = rispy.load(f)

    # clean db
    logger.info("Cleaning up MongoDB collections")
    bntl_client.bntl_coll.drop()
    bntl_client.query_coll.drop()
    logger.info("Cleaning up QDrant collections")
    vector_client.qdrant_client.delete_collection(vector_client.collection_name)

    # insert documents
    logger.info("Inserting {} docs from file: {}".format(len(data), args.ris_file))
    insert_documents(bntl_client.bntl_coll, data)
    logger.info("Creating text indices")
    create_text_index(bntl_client)
    docs = list(bntl_client.bntl_coll.find())

    from FlagEmbedding import BGEM3FlagModel

    model = BGEM3FlagModel('BAAI/bge-m3', use_fp16=True)
    # Setting use_fp16 to True speeds up computation with a slight performance degradation

    # from sentence_transformers import SentenceTransformer
    # query_prompt_name = "s2s_query"
    batch_size = 1_000

    # model = SentenceTransformer("dunzhang/stella_en_400M_v5", trust_remote_code=True).cuda()

    logger.info("Encoding documents")
    for i in tqdm.tqdm(range(0, len(docs), batch_size)):
        texts = [convert_to_text(get_doc_text(doc), ignore_keywords=True) for doc in docs[i:i+batch_size]]
        # embeddings = model.encode(
        #     texts, prompt_name=query_prompt_name, show_progress_bar=True)
        embeddings = model.encode(texts, batch_size=12)["dense_vecs"]
        doc_ids = [str(doc["_id"]) for doc in docs]
        vector_client.insert(embeddings, doc_ids)
    
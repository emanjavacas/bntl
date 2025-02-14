
import asyncio
import glob
import sys
sys.path.append("./")

from bntl.rdf import parse_rdf
from bntl.db import DBClient
from bntl.vector_db import VectorClient
from bntl.vectorization import vectorize_task, Status
from bntl.models import DocumentModel


async def main():
    db_client = DBClient()
    vector_client = VectorClient()

    for path in glob.glob("test/docs/*rdf"):
        with open(path) as f:
            docs = parse_rdf(f.read())
            docs = list(sorted(docs, key=lambda doc: doc["id"]))

        await db_client.insert_documents(docs)
        docs_found = await db_client.find({"document.id": {"$in": [doc["id"] for doc in docs]}})
        docs_found = sorted([doc["document"] for doc in docs_found], key=lambda doc: doc["id"])
        assert [DocumentModel.model_validate(doc).model_dump() for doc in docs] == docs_found

    task_id = "test-task"
    await db_client.register_vectorization(task_id, Status.VECTORIZING)
    await vectorize_task(db_client, vector_client, task_id)

    for doc in docs:
        result = await vector_client.find_vector_by_id(doc["id"])
        assert result[0].payload["doc_id"] == doc["id"]


if __name__ == '__main__':
    asyncio.run(main())
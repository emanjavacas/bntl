
from typing import List

from tqdm import tqdm

import numpy as np
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct
from qdrant_client import models

from bntl.settings import settings


class MissingVectorException(Exception):
    pass


class VectorClient:
    """
    Client for a Vector database using QDrant
    """
    def __init__(self) -> None:
        self.qdrant_client = AsyncQdrantClient(location="localhost", port=settings.QDRANT_PORT)
        self.collection_name = settings.QDRANT_COLL

    async def search(self, doc_id, limit=10):
        """
        Find top-k (`limit`) nearest neighbors to the given `doc_id`
        """
        hits, _ = await self.qdrant_client.scroll(self.collection_name, scroll_filter=models.Filter(
            must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))]),
            with_vectors=True)
        if len(hits) == 0:
            raise MissingVectorException("Unknown document: {}".format(doc_id))
        hits = await self.qdrant_client.search(
            collection_name=self.collection_name, 
            query_vector=hits[0].vector,
            limit=limit + 1)
        _, *hits = hits # skip self similarity
        return [{"doc_id": hit.payload["doc_id"], "score": hit.score} for hit in hits]

    async def insert(self, vectors:List[float], ids:List[str], batch_size=1000):
        assert len(vectors) == len(ids)
        vectors = np.array(vectors)
        if not await self.qdrant_client.collection_exists(self.collection_name):
            await self.qdrant_client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=vectors.shape[1], distance=Distance.COSINE))
            await self.qdrant_client.create_payload_index(
                collection_name=self.collection_name,
                field_name="doc_id",
                field_schema="uuid")
        cur = (await self.qdrant_client.count(self.collection_name)).count
        for i in tqdm(range(0, vectors.shape[0], batch_size)):
            await self.qdrant_client.upsert(
                collection_name=self.collection_name,
                points=[
                    PointStruct(
                            id=cur + idx, # vector index in the database
                            vector=vector.tolist(),
                            payload={"doc_id": ids[idx]})
                    for idx, vector in enumerate(vectors[i:i+batch_size])])
            cur += batch_size

        return True
    
    async def get_vectors(self, limit=300_000):
        return await self.qdrant_client.scroll(
            collection_name=self.collection_name,
            limit=limit,
            with_payload=True,
            with_vectors=False)
    
    async def _clear_up(self):
        await self.qdrant_client.delete_collection(self.collection_name)
    
    async def close(self):
        await self.qdrant_client.close()


# doc_id = "66d5df1d51c4fabc4fbf9dc5"
# hits, _ = await self.qdrant_client.scroll(self.collection_name, scroll_filter=models.Filter(
#      must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))]),
#      with_vectors=True)

# self.qdrant_client.
# (await self.qdrant_client.count(self.collection_name)).count
# c = VectorClient()
# self = c
# vectors = await c.get_vectors()
# len(vectors[0])
# ids = [vec.payload["doc_id"] for vec in vectors[0]]

# from bntl.db import DBClient
# d = await DBClient.create()
# docs = await d.find()
# _ids = [str(doc["_id"]) for doc in docs]
# len(_ids) == len(ids)
# set(_ids) == set(ids)
# len(set(_ids).intersection(set(ids)))
# set(_ids).difference(set(ids))

# len(vectors[0])
# ids = [vec.payload["doc_id"] for vec in vectors[0]]
# docs = await db.find()
# _ids = [str(doc['_id']) for doc in docs]
# len(set(_ids))
# len(set(ids))
# set([type(id) for id in _ids])

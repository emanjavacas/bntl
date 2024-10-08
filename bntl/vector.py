
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
        self.qdrant_client = AsyncQdrantClient(
            location="localhost", port=settings.QDRANT_PORT, timeout=100)
        self.collection_name = settings.QDRANT_COLL

    async def find_vector_by_id(self, doc_id):
        hits, _ = await self.qdrant_client.scroll(self.collection_name, scroll_filter=models.Filter(
            must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))]),
            with_vectors=True)
        return hits

    async def search(self, doc_id, limit=10):
        """
        Find top-k (`limit`) nearest neighbors to the given `doc_id`
        """
        hits = await self.find_vector_by_id(doc_id)        
        if len(hits) == 0:
            raise MissingVectorException("Unknown document: {}".format(doc_id))
        hits = await self.qdrant_client.search(
            collection_name=self.collection_name, 
            query_vector=hits[0].vector,
            limit=limit + 1)
        _, *hits = hits # skip self similarity
        return [{"doc_id": hit.payload["doc_id"], "score": hit.score} for hit in hits]

    async def count(self):
        return (await self.qdrant_client.count(self.collection_name)).count

    async def insert(self, vectors, doc_ids, batch_size=500):
        """
        Vector ingestion logic
        """
        assert len(vectors) == len(doc_ids)
        vectors = np.array(vectors)
        if not await self.qdrant_client.collection_exists(self.collection_name):
            await self.qdrant_client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=vectors.shape[1], distance=Distance.COSINE))
            await self.qdrant_client.create_payload_index(
                collection_name=self.collection_name,
                field_name="doc_id",
                field_schema="uuid")

        cur = await self.count()
        for i in tqdm(range(0, vectors.shape[0], batch_size)):
            points = []
            for v_id, vector in enumerate(vectors[i:i+batch_size]):
                points.append(PointStruct(
                    id=cur + i + v_id,
                    vector=vector.tolist(),
                    payload={"doc_id": doc_ids[i + v_id]}))
            await self.qdrant_client.upsert(
                collection_name=self.collection_name,
                points=points)

        return True
    
    async def get_vectors(self):
        """
        Utility function to retrieve vectors from the database
        """
        hits, _ = await self.qdrant_client.scroll(
            self.collection_name, with_vectors=False, limit=500_000)
        return hits
    
    async def _clear_up(self):
        await self.qdrant_client.delete_collection(self.collection_name)
    
    async def close(self):
        await self.qdrant_client.close()
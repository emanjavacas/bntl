
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct
from qdrant_client import models

from tqdm import tqdm
import numpy as np

from bntl.settings import settings


class VectorClient:
    def __init__(self) -> None:
        self.qdrant_client = QdrantClient(location="localhost", port=settings.QDRANT_PORT)
        self.collection_name = settings.QDRANT_COLL

    def search(self, doc_id, limit=10):
        hits, _ = self.qdrant_client.scroll(self.collection_name, scroll_filter=models.Filter(
            must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))]),
            with_vectors=True)
        if len(hits) == 0:
            raise ValueError("Unknown document: {}".format(doc_id))
        hits = self.qdrant_client.search(
            collection_name=self.collection_name, 
            query_vector=hits[0].vector,
            limit=limit + 1)
        _, *hits = hits # skip self similarity
        return [{"doc_id": hit.payload["doc_id"], "score": hit.score} for hit in hits]

    def insert(self, vectors, ids, batch_size=1000):
        if not self.qdrant_client.collection_exists(self.collection_name):
            self.qdrant_client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=vectors.shape[1], distance=Distance.COSINE))

        cur = 0
        for i in tqdm(range(0, vectors.shape[0], batch_size)):
            self.qdrant_client.upsert(
                collection_name=self.collection_name,
                points=[
                    PointStruct(
                            id=cur + idx, vector=vector.tolist(),
                            payload={"doc_id": ids[cur + idx]})
                    for idx, vector in enumerate(vectors[i:i+batch_size])])
            cur += batch_size

        return True
    
    def close(self):
        self.qdrant_client.close()


if __name__ == "__main__":
    self = VectorClient()
    self.insert(vectors, ids)
    self.qdrant_client.delete_collection(settings.QDRANT_COLL)

    vectors = np.load("data_no_keyword.npy")["embeddings"]
    ids = np.load("data_no_keyword.npy")["ids"]


    coll_name = "bntl"
    # client.delete_collection(coll_name)


    client.delete_collection(coll_name)
    coll = client.get_collection(coll_name)
    coll.indexed_vectors_count

    client.search(
    collection_name=coll_name,
    query_vector=vectors[21010],
    limit=5  # Return 5 closest points
    )

    client.search(collection_name=coll_name, with_payload={"_id": "66b4fc4321c5d2c5d7f453d0"})

    idx=969;docs[idx]["title"],docs[idx].get("keywords")

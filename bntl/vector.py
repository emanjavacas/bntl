
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct

import numpy as np
import rispy

with open("merged.ris") as f:
    docs = rispy.load(f)

vectors = np.load("merged.npy")
vectors.shape

client = QdrantClient(location="localhost", port=6333)

coll_name = "bntl"
if not client.collection_exists(coll_name):
   client.create_collection(
      collection_name=coll_name,
      vectors_config=VectorParams(size=vectors.shape[1], distance=Distance.COSINE))

cur = 0
batch_size = 1000
for i in range(0, vectors.shape[1], batch_size):
    client.upsert(
    collection_name=coll_name,
    points=[
        PointStruct(
                id=cur + idx, vector=vector.tolist())
        for idx, vector in enumerate(vectors[i:i+batch_size])])
    cur += batch_size

coll = client.get_collection(coll_name)
coll.indexed_vectors_count

client.search(
   collection_name=coll_name,
   query_vector=vectors[0],
   limit=5  # Return 5 closest points
)
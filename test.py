
from pymongo.mongo_client import MongoClient
from pymongo import errors

import rispy
import logging

from bntl.settings import settings
from bntl.db_client import AtlasClient



if __name__ == '__main__':
    with open('merged.ris', 'r') as f:
        db = rispy.load(f)

    sample = db[:100]
    client = AtlasClient()
    # client.update_documents(settings.MONGODB_BNTL_COLL, db)
    client.database.list_collection_names()
    items = client.find(limit=10000000)
    items = list(client.find())
    len(items)

    # test stuff    
    for item in items:
       if 'authors' not in item:
            if 'first_authors' not in item:
                assert 'secondary_authors' in item

    first, *rest = items
    keys = set(first.keys())
    for item in rest:
        keys = keys.intersection(set(item.keys()))
    keys

    keys = set(first.keys())
    for item in rest:
        keys = keys.union(set(item.keys()))
    keys

    [item for item in items if 'access_date' in item]

    import collections
    counts = collections.Counter()
    for it in db:
        fields = []
        for key in ['title', 'type_of_reference', 'year', 'authors', 'first_authors', 'secondary_authors']:
            value = it.get(key, (None,))
            if isinstance(value, list):
                value = tuple(value)
            fields.append(value)
        counts[tuple(fields)] += 1


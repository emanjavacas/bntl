
import os
import asyncio

from bntl.db import DBClient
from bntl.vector import VectorClient
from bntl.settings import settings
from vectorizer.db import DBClient as VectorizerDBClient


async def main():
    db_client = await DBClient.create()
    await db_client._clear_up()

    vector_client = VectorClient()
    await vector_client._clear_up()
    db_client = await VectorizerDBClient.create()
    await db_client._clear_up()

    if os.path.isdir(settings.UPLOAD_LOG_DIR):
        for f in os.listdir(settings.UPLOAD_LOG_DIR):
            os.remove(os.path.join(settings.UPLOAD_LOG_DIR, f))

    # TODO: remove revectorize-* files

if __name__ == '__main__':
    asyncio.run(main())
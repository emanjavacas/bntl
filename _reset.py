
import os
import asyncio

from bntl.db import DBClient
from bntl.vector_db import VectorClient
from bntl.settings import settings


async def main():
    db_client = await DBClient.create()
    await db_client._clear_up()
    vector_client = VectorClient()
    await vector_client._clear_up()

    if os.path.isdir(settings.UPLOAD_LOG_DIR):
        for f in os.listdir(settings.UPLOAD_LOG_DIR):
            os.remove(os.path.join(settings.UPLOAD_LOG_DIR, f))
    if os.path.isdir(settings.VECTORIZE_LOG_DIR):
        for f in os.listdir(settings.VECTORIZE_LOG_DIR):
            os.remove(os.path.join(settings.VECTORIZE_LOG_DIR, f))

if __name__ == '__main__':
    asyncio.run(main())

import asyncio

async def maybe_await(value):
    if asyncio.iscoroutine(value):
        return await value
    return value

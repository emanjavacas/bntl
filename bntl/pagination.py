
from typing import Generic, List, TypeVar, Callable

from pydantic import BaseModel, Field


T = TypeVar("T")


class PagedResponseSchema(BaseModel, Generic[T]):
    total: int
    page: int
    from_page: int
    to_page: int
    total_pages: int
    size: int
    items: List[T]


def identity(item): return item


def paginate(coll, query, ResponseSchema: BaseModel, 
             page: int=Field(1, ge=1),
             size: int=Field(10, le=100),
             transform: Callable=identity) -> PagedResponseSchema[T]:
    results = coll.find(query).skip((page - 1) * size).limit(size)
    total = coll.count_documents(query)
    total_pages = total // size
    from_page = max(1, page - 4)
    to_page = min(total_pages, page + 4)
    return PagedResponseSchema(
        total=total,
        page=page,
        from_page=from_page,
        to_page=to_page,
        total_pages=total_pages,
        size=size,
        items=[transform(ResponseSchema.from_orm(item)) for item in results])
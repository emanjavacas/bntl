
from typing import Optional

from pydantic import BaseModel


class SearchQuery(BaseModel):
    """
    """
    type_of_reference: Optional[str] = None
    title: Optional[str] = None
    year: Optional[str] = None
    author: Optional[str] = None
    keywords: Optional[str] = None
    use_regex_author: Optional[bool] = False
    use_regex_title: Optional[bool] = False
    use_regex_keywords: Optional[bool] = False


def build_query(type_of_reference=None,
                title=None,
                year=None,
                author=None,
                keywords=None,
                use_regex_title=False,
                use_regex_author=False,
                use_regex_keywords=False):
    """
    """

    query = []

    if type_of_reference is not None:
        query.append({"type_of_reference": type_of_reference})

    if title is not None:
        title = title if not use_regex_title else {"$regex": title}
        query.append({"$or": [{"title": title},
                              {"secondary_title": title},
                              {"tertiary_title": title}]})

    if year is not None:
        if "-" in year: # year range
            start, end = year.split('-')
            start, end = int(start), int(end)
            query.append({"$or": [{"$and": [{"year": {"$gte": start}},
                                            {"year": {"$lt": end}}]},
                                  {"$and": [{"end_year": {"$gte": start}},
                                            {"end_year": {"$lt": end}}]}]})
        else:
            query.append({"$and": [{"year": {"$gte": int(year)}},
                                   {"end_year": {"$lte": int(year) + 1}}]})

    if author is not None:
        author = author if not use_regex_author else {"$regex": author}
        query.append({"$or": [{"authors": author},
                              {"first_authors": author},
                              {"secondary_authors": author},
                              {"tertiary_authors": author}]})

    if keywords is not None:
        keywords = keywords if not use_regex_keywords else {"$regex": keywords}
        query.append({"keywords": keywords})

    if len(query) > 1:
        query = {"$and": query}
    elif len(query) == 1:
        query = query[0]
    else:
        query = {}

    return query

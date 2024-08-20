
import urllib
import re


class YearFormatException(Exception):
    pass


def fix_year(doc):
    """
    Utility function dealing with different input formats for the year field.
    """
    try:
        int(doc['year'])
        doc['end_year'] = int(doc['year']) + 1 # year is uninclusive
        return doc
    except Exception:
        # undefined years (eg. 197X), go for average value
        if 'X' in doc['year']:
            doc['year'] = doc['year'].replace('X', '5')
        # range years (eg. 1987-2024, 1987-, ...)
        if '-' in doc['year']:
            m = re.match(r"([0-9]{4})-([0-9]{4})?", doc['year'])
            if not m: # error, skip the record
                raise YearFormatException(doc['year'])
            start, end = m.groups()
            doc['year'] = start
            doc['end_year'] = end or int(start) + 1 # use starting date if end year is missing

    return doc


def identity(item): return item


def is_atlas(uri):
    """
    Check if the current URI corresponds to a Cloud Atlas database
    """
    return urllib.parse.urlparse(uri).netloc.endswith("mongodb.net")

import glob
import sys
sys.path.append("./")

import rispy

from bntl import utils
from bntl.rdf import parse_rdf
from bntl.models import DocumentModel


if __name__ == "__main__":
    paths = glob.glob("test/docs/*rdf")
    for path in paths:
        # read data from file
        with open(path, 'r') as f:
            parsed = parse_rdf(f.read())
            for doc in parsed:
                DocumentModel.model_validate(doc)
            docs = rispy.dumps(parsed, mapping=utils.RISPY_MAPPING)
            

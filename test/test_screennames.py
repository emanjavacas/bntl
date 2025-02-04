
import re
import pandas as pd
import rispy

import sys
sys.path.append("./")
from bntl import utils
from bntl.rdf import parse_rdf
from bntl.models import get_record_screen_name

import difflib
from termcolor import colored


def generate_diff(str1, str2, output_file="diff_output.txt"):
    """Generate a visually aligned character-level diff with a reference on top,
    a middle line showing dropped ('<') and added ('>') characters in color,
    and the compared string on the bottom, keeping alignment."""
    diff = list(difflib.ndiff(str1, str2))
    reference_line = []
    change_line = []
    compared_line = []
    
    for char in diff:
        if char.startswith(" "):
            reference_line.append(char[2:])
            change_line.append(" ")
            compared_line.append(char[2:])
        elif char.startswith("-"):
            reference_line.append(char[2:])
            change_line.append(colored("<", "red"))
            compared_line.append(" ")  # Maintain alignment
        elif char.startswith("+"):
            reference_line.append(" ")  # Maintain alignment
            change_line.append(colored(">", "green"))
            compared_line.append(char[2:])
    
    ref_text = "".join(reference_line)
    change_text = "".join(change_line)
    comp_text = "".join(compared_line)
    
    return f"{ref_text}\n{change_text}\n{comp_text}"


if __name__ == "__main__":
    data = pd.read_csv("test/screen/screennames.csv", sep=";")
    data = data.dropna()

    ris = []
    with open("test/screen/sample_formulas.rdf") as f:
        for m in re.findall(r"<rdf:RDF.*?</rdf:RDF>", f.read(), re.DOTALL):
            ris_data = rispy.loads(parse_rdf(m), mapping=utils.RISPY_MAPPING)
            ris.extend(ris_data)

    screen = []
    for item in ris:
        screen.append({"DOC ID": item['id'], 'generated': get_record_screen_name(item), "type": item["type_of_reference"]})
    merged = pd.merge(data, pd.DataFrame.from_dict(screen), on="DOC ID")

    with open("screennames_diff.txt", "w+") as f:
        for _, (doc_id, generated, ref, reftype) in merged[["DOC ID", "generated", "Screen names", "type"]].iterrows():
            if generated == ref: continue
            diff = generate_diff(ref, generated)
            f.write(f"- Doc Id: {doc_id}; Reference Type: {reftype}\n")
            f.write(diff + '\n')
            f.write("\n")
            
    # item = merged.loc[2][["Screen", "Screen names", "ris"]].to_dict(); print(rispy.dumps([item.pop("ris")])); item

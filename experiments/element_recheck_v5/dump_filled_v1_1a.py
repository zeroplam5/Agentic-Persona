"""Dump every cell of the filled v1.1a workbooks (read-only; no inference, no edits).

Usage: python -I dump_filled_v1_1a.py <xlsx> <out_dir>
Writes <out_dir>/<stem>__<sheet>.csv with columns ref,row,col,value (raw strings).
"""
import csv, os, re, sys, zipfile
import xml.etree.ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
RELNS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def col2n(c):
    n = 0
    for ch in c:
        n = n * 26 + ord(ch) - 64
    return n


def text_of(el):
    return "".join(t.text or "" for t in el.iter("{%s}t" % NS["m"]))


def dump(path, out_dir):
    z = zipfile.ZipFile(path)
    ss = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        ss = [text_of(si) for si in root.findall("m:si", NS)]
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rmap = {r.get("Id"): r.get("Target") for r in rels.iter(RELNS + "Relationship")}
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    stem = os.path.splitext(os.path.basename(path))[0]
    os.makedirs(out_dir, exist_ok=True)
    for sh in wb.find("m:sheets", NS):
        name = sh.get("name")
        tgt = rmap[sh.get("{%s}id" % NS["r"])].lstrip("/")
        tgt = tgt if tgt.startswith("xl/") else "xl/" + tgt
        root = ET.fromstring(z.read(tgt))
        rows = []
        for c in root.iter("{%s}c" % NS["m"]):
            ref = c.get("r"); t = c.get("t")
            v = c.find("m:v", NS)
            if t == "s" and v is not None:
                val = ss[int(v.text)]
            elif t == "inlineStr":
                val = text_of(c)
            elif v is not None:
                val = v.text
            else:
                continue
            m = re.match(r"([A-Z]+)(\d+)", ref)
            rows.append((ref, int(m.group(2)), col2n(m.group(1)), val))
        safe = re.sub(r"[^\w가-힣]+", "_", name)
        out = os.path.join(out_dir, f"{stem}__{safe}.csv")
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f); w.writerow(["ref", "row", "col", "value"]); w.writerows(rows)
        dv = root.find("m:dataValidations", NS)
        print(f"{name}: {len(rows)} cells, dims={root.find('m:dimension', NS).get('ref') if root.find('m:dimension', NS) is not None else '?'}, "
              f"validations={'yes' if dv is not None else 'no'} -> {out}")


if __name__ == "__main__":
    dump(sys.argv[1], sys.argv[2])

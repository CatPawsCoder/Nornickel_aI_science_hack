# -*- coding: utf-8 -*-
"""Параллельная сборка графа: multiprocessing-споттинг + Kùzu COPY FROM CSV."""
import csv
import json
import os
import sys
import time
from multiprocessing import Pool

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ontology"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from thesaurus import MATERIALS, PROCESSES, EQUIPMENT, FACILITIES
from graph import open_db, q, ROOT
from spot_worker import process_doc

CACHE = os.path.join(ROOT, "data", "cache")
TMP = os.path.join(CACHE, "csv")
os.makedirs(TMP, exist_ok=True)


def source_type_of(filename):
    fn = filename.lower()
    if "патент" in fn or "patent" in fn:
        return "patent", "high"
    if "цветные металлы" in fn or "cm_" in fn or "журнал" in fn:
        return "journal", "high"
    if fn.startswith(("оип", "ои ", "ои-")) or "обзор" in fn:
        return "internal_review", "high"
    return "review", "medium"


def w_csv(name, header, rows):
    path = os.path.join(TMP, name)
    with open(path, "w", encoding="utf-8", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(header)
        wr.writerows(rows)
    return path.replace("\\", "/")


def main():
    t0 = time.time()
    conn = open_db(fresh=True)

    for cid, m in MATERIALS.items():
        conn.execute("MERGE (n:Material {id:$id}) SET n.name=$n, n.name_en=$e, n.kind=$k",
                     {"id": cid, "n": m["name"], "e": m.get("en", ""), "k": m.get("kind", "")})
    for cid, m in PROCESSES.items():
        conn.execute("MERGE (n:Process {id:$id}) SET n.name=$n, n.name_en=$e, n.domain=$d",
                     {"id": cid, "n": m["name"], "e": m.get("en", ""), "d": m.get("domain", "")})
    for cid, m in EQUIPMENT.items():
        conn.execute("MERGE (n:Equipment {id:$id}) SET n.name=$n, n.name_en=$e",
                     {"id": cid, "n": m["name"], "e": m.get("en", "")})
    for cid, m in FACILITIES.items():
        conn.execute("MERGE (n:Facility {id:$id}) SET n.name=$n, n.geo=$g",
                     {"id": cid, "n": m["name"], "g": m.get("geo", "")})
    print(f"entities {time.time()-t0:.1f}s", flush=True)

    docs = [json.loads(l) for l in open(os.path.join(CACHE, "docs.jsonl"), encoding="utf-8")]
    print(f"docs: {len(docs)}", flush=True)

    pub_rows = []
    for d in docs:
        st, cred = source_type_of(d["filename"])
        pub_rows.append([d["id"], d["title"][:200], d["year"] or 0, d["lang"],
                         d["geo_hint"], st, cred, d["filename"][:200]])
    p = w_csv("pub.csv", ["id", "title", "year", "lang", "geo", "source_type", "credibility", "filename"], pub_rows)
    conn.execute(f'COPY Publication FROM "{p}" (HEADER=true)')
    print(f"publications COPY {time.time()-t0:.1f}s", flush=True)

    tasks = [(d["id"], d["filename"], d["text_path"], ROOT) for d in docs]
    men_m, men_p, men_e, men_f = [], [], [], []
    cond_rows, hascond_rows, aboutm_rows, aboutp_rows = [], [], [], []
    men_bucket = {"Material": men_m, "Process": men_p, "Equipment": men_e, "Facility": men_f}
    cond_i = 0
    nproc = max(2, (os.cpu_count() or 4) - 2)
    print(f"spotting with {nproc} processes...", flush=True)
    with Pool(nproc) as pool:
        for k, res in enumerate(pool.imap_unordered(process_doc, tasks, chunksize=8)):
            did = res["doc_id"]
            for etype, cid, n in res["mentions"]:
                men_bucket[etype].append([did, cid, n])
            for (param, subst, op, v, v2, unit, quote, ctx, mcid, pcid) in res["conds"]:
                cid_ = f"c{cond_i}"
                # переносы строк ломают параллельный CSV-ридер Kùzu -> нормализуем в пробелы
                quote = " ".join(quote.split())
                ctx = " ".join(ctx.split())
                cond_rows.append([cid_, param, subst, op, v, v2, unit, quote, ctx, did, True])
                hascond_rows.append([did, cid_])
                if mcid:
                    aboutm_rows.append([cid_, mcid])
                if pcid:
                    aboutp_rows.append([cid_, pcid])
                cond_i += 1
            if (k + 1) % 300 == 0:
                print(f"  {k+1}/{len(tasks)}  conds={cond_i}  {time.time()-t0:.1f}s", flush=True)

    for name, rows, rel in [("men_m", men_m, "MENTIONS"), ("men_p", men_p, "MENTIONS_P"),
                            ("men_e", men_e, "MENTIONS_E"), ("men_f", men_f, "MENTIONS_F")]:
        if rows:
            pp = w_csv(name + ".csv", ["from", "to", "count"], rows)
            conn.execute(f'COPY {rel} FROM "{pp}" (HEADER=true)')
    print(f"mentions COPY {time.time()-t0:.1f}s", flush=True)

    pc = w_csv("cond.csv", ["id", "param", "substance", "op", "value", "value2",
                            "unit", "quote", "context", "doc_id", "verified"], cond_rows)
    conn.execute(f'COPY Condition FROM "{pc}" (HEADER=true, PARALLEL=false)')
    ph = w_csv("hascond.csv", ["from", "to"], hascond_rows)
    conn.execute(f'COPY HAS_CONDITION FROM "{ph}" (HEADER=true)')
    if aboutm_rows:
        conn.execute(f'COPY ABOUT_M FROM "{w_csv("aboutm.csv", ["from","to"], aboutm_rows)}" (HEADER=true)')
    if aboutp_rows:
        conn.execute(f'COPY ABOUT_P FROM "{w_csv("aboutp.csv", ["from","to"], aboutp_rows)}" (HEADER=true)')
    print(f"conditions COPY {time.time()-t0:.1f}s  ({len(cond_rows)} conds)", flush=True)

    for tbl in ("Publication", "Material", "Process", "Equipment", "Facility", "Condition"):
        print(f"  {tbl}: {q(conn, f'MATCH (n:{tbl}) RETURN count(n) AS c')[0]['c']}")
    for rel in ("MENTIONS", "MENTIONS_P", "MENTIONS_E", "MENTIONS_F", "HAS_CONDITION", "ABOUT_M"):
        print(f"  {rel}: {q(conn, f'MATCH ()-[r:{rel}]->() RETURN count(r) AS c')[0]['c']}")
    print(f"TOTAL {time.time()-t0:.1f}s", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()

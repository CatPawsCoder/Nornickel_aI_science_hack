# -*- coding: utf-8 -*-
"""Быстрая сборка графа на полном корпусе через Kùzu COPY FROM CSV.

Вместо ~1M одиночных INSERT — несколько bulk-COPY операций.
Слои:
  1. Сущности тезауруса (MERGE, их мало)
  2. Publication + MENTIONS* (споттинг) — bulk
  3. Condition + HAS_CONDITION + ABOUT_M (числа) — bulk
  4. LLM-claims (merge_extracted.py запускается отдельно после)
"""
import csv
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ontology"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from thesaurus import MATERIALS, PROCESSES, EQUIPMENT, FACILITIES, build_matcher, spot
from graph import open_db, q, ROOT
from numeric import extract_numeric_facts, validate_fact

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

    # --- 1. сущности тезауруса ---
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

    # --- 2. публикации ---
    pub_rows = []
    for d in docs:
        st, cred = source_type_of(d["filename"])
        pub_rows.append([d["id"], d["title"][:200], d["year"] or 0, d["lang"],
                         d["geo_hint"], st, cred, d["filename"][:200]])
    p = w_csv("pub.csv", ["id", "title", "year", "lang", "geo", "source_type", "credibility", "filename"], pub_rows)
    conn.execute(f'COPY Publication FROM "{p}" (HEADER=true)')
    print(f"publications COPY {time.time()-t0:.1f}s", flush=True)

    # --- 3. споттинг сущностей -> MENTIONS* ---
    matchers = build_matcher()
    men_m, men_p, men_e, men_f = [], [], [], []
    cond_rows, hascond_rows, aboutm_rows, aboutp_rows = [], [], [], []
    subst_map = {}
    for cid, m in MATERIALS.items():
        for v in [m["name"], *(m.get("syn") or [])]:
            subst_map[v.lower()] = cid
    param_proc = {"плотность тока": "electrowinning", "выход по току": "electrowinning",
                  "сухой остаток": "desalination", "крупность": "grinding"}

    # Капы против биржевых XLS и огромных сборников:
    #  - споттинг/числа только по первым SPOT_LIMIT символам (ключевой контент в начале)
    #  - не более MAX_COND_PER_DOC атрибутированных числовых фактов на документ
    SPOT_LIMIT = 300_000
    MAX_COND_PER_DOC = 300
    PRICE_NOISE = ("prices", "quarterly", "lme", "forecast")

    cond_i = 0
    for di, d in enumerate(docs):
        try:
            text = open(os.path.join(ROOT, d["text_path"]), encoding="utf-8").read()
        except Exception:
            continue
        fn_low = d["filename"].lower()
        is_price = any(k in fn_low for k in PRICE_NOISE)
        scan_text = text[:SPOT_LIMIT]
        hits = spot(scan_text, matchers)
        for (etype, cid), n in hits.items():
            row = [d["id"], cid, n]
            {"Material": men_m, "Process": men_p, "Equipment": men_e, "Facility": men_f}[etype].append(row)
        # числа — пропускаем ценовые XLS-таблицы (чистый шум) целиком
        if not is_price:
            doc_conds = 0
            for f in extract_numeric_facts(scan_text):
                if doc_conds >= MAX_COND_PER_DOC:
                    break
                fd = f.to_dict()
                if fd["param"] == "параметр" and not fd["substance"]:
                    continue
                if not validate_fact(fd, text):
                    continue
                cid_ = f"c{cond_i}"
                cond_rows.append([cid_, fd["param"], fd["substance"], fd["op"], fd["value"],
                                  fd["value2"] if fd["value2"] is not None else -1.0,
                                  fd["unit"], fd["quote"][:200], fd["context"][:300], d["id"], True])
                hascond_rows.append([d["id"], cid_])
                mcid = subst_map.get(fd["substance"].lower())
                if mcid:
                    aboutm_rows.append([cid_, mcid])
                pcid = param_proc.get(fd["param"])
                if pcid:
                    aboutp_rows.append([cid_, pcid])
                cond_i += 1
                doc_conds += 1
        if (di + 1) % 300 == 0:
            print(f"  spotted {di+1}/{len(docs)}  conds={cond_i}", flush=True)

    # bulk COPY mentions
    for name, rows, rel in [("men_m", men_m, "MENTIONS"), ("men_p", men_p, "MENTIONS_P"),
                            ("men_e", men_e, "MENTIONS_E"), ("men_f", men_f, "MENTIONS_F")]:
        if rows:
            pp = w_csv(name + ".csv", ["from", "to", "count"], rows)
            conn.execute(f'COPY {rel} FROM "{pp}" (HEADER=true)')
    print(f"mentions COPY {time.time()-t0:.1f}s", flush=True)

    # bulk COPY conditions
    pc = w_csv("cond.csv", ["id", "param", "substance", "op", "value", "value2",
                            "unit", "quote", "context", "doc_id", "verified"], cond_rows)
    conn.execute(f'COPY Condition FROM "{pc}" (HEADER=true)')
    ph = w_csv("hascond.csv", ["from", "to"], hascond_rows)
    conn.execute(f'COPY HAS_CONDITION FROM "{ph}" (HEADER=true)')
    if aboutm_rows:
        pa = w_csv("aboutm.csv", ["from", "to"], aboutm_rows)
        conn.execute(f'COPY ABOUT_M FROM "{pa}" (HEADER=true)')
    if aboutp_rows:
        pap = w_csv("aboutp.csv", ["from", "to"], aboutp_rows)
        conn.execute(f'COPY ABOUT_P FROM "{pap}" (HEADER=true)')
    print(f"conditions COPY {time.time()-t0:.1f}s  ({len(cond_rows)} conds)", flush=True)

    # --- статистика ---
    for tbl in ("Publication", "Material", "Process", "Equipment", "Facility", "Condition"):
        print(f"  {tbl}: {q(conn, f'MATCH (n:{tbl}) RETURN count(n) AS c')[0]['c']}")
    for rel in ("MENTIONS", "MENTIONS_P", "MENTIONS_E", "MENTIONS_F", "HAS_CONDITION", "ABOUT_M"):
        print(f"  {rel}: {q(conn, f'MATCH ()-[r:{rel}]->() RETURN count(r) AS c')[0]['c']}")
    print(f"TOTAL {time.time()-t0:.1f}s", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()

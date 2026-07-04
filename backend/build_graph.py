# -*- coding: utf-8 -*-
"""Сборка графа знаний из детерминированных слоёв:
1. Publication  <- docs.jsonl
2. Material/Process/Equipment/Facility <- тезаурус
3. MENTIONS*    <- словарный споттинг по корпусу
4. Condition    <- numeric_facts.jsonl (+ ABOUT_M/ABOUT_P по контексту)
5. (позже) Claims и семантические связи <- LLM-слой (extracted.jsonl)
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ontology"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from thesaurus import MATERIALS, PROCESSES, EQUIPMENT, FACILITIES, build_matcher, spot
from graph import open_db, q, ROOT

CACHE = os.path.join(ROOT, "data", "cache")

# карта источника по имени файла (для credibility)
def source_type_of(filename: str) -> tuple[str, str]:
    fn = filename.lower()
    if fn.startswith(("оип", "ои ", "ои-", "ис-")):
        return "internal_review", "high"       # внутренний обзор института
    if "патент" in fn or "patent" in fn:
        return "patent", "high"
    if fn.endswith(".pdf") and any(w in fn for w in ("журнал", "вестник", "journal")):
        return "journal", "high"
    return "review", "medium"


def main(fresh: bool = True) -> None:
    t0 = time.time()
    conn = open_db(fresh=fresh)

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
    print(f"entities loaded {time.time()-t0:.1f}s", flush=True)

    # --- 2. публикации + споттинг ---
    matchers = build_matcher()
    docs = [json.loads(l) for l in open(os.path.join(CACHE, "docs.jsonl"), encoding="utf-8")]
    rel_of = {"Material": "MENTIONS", "Process": "MENTIONS_P",
              "Equipment": "MENTIONS_E", "Facility": "MENTIONS_F"}
    spots_dump = {}
    for d in docs:
        st, cred = source_type_of(d["filename"])
        conn.execute(
            "MERGE (p:Publication {id:$id}) SET p.title=$t, p.year=$y, p.lang=$l, "
            "p.geo=$g, p.source_type=$st, p.credibility=$c, p.filename=$f",
            {"id": d["id"], "t": d["title"], "y": d["year"] or 0, "l": d["lang"],
             "g": d["geo_hint"], "st": st, "c": cred, "f": d["filename"]})
        text = open(os.path.join(ROOT, d["text_path"]), encoding="utf-8").read()
        hits = spot(text, matchers)
        spots_dump[d["id"]] = {f"{et}:{cid}": n for (et, cid), n in hits.items()}
        for (etype, cid), n in hits.items():
            conn.execute(
                f"MATCH (p:Publication {{id:$pid}}), (x:{etype} {{id:$cid}}) "
                f"MERGE (p)-[r:{rel_of[etype]}]->(x) SET r.count=$n",
                {"pid": d["id"], "cid": cid, "n": n})
    with open(os.path.join(CACHE, "spots.json"), "w", encoding="utf-8") as f:
        json.dump(spots_dump, f, ensure_ascii=False)
    print(f"publications+mentions loaded {time.time()-t0:.1f}s", flush=True)

    # --- 3. числовые условия ---
    # substance-строка из numeric.py -> canon id материала
    subst_map = {}
    for cid, m in MATERIALS.items():
        for v in [m["name"], *(m.get("syn") or [])]:
            subst_map[v.lower()] = cid
    # param -> процесс-хинт (для ABOUT_P)
    param_proc = {
        "плотность тока": "electrowinning", "выход по току": "electrowinning",
        "сухой остаток": "desalination", "крупность": "grinding",
    }

    facts = [json.loads(l) for l in open(os.path.join(CACHE, "numeric_facts.jsonl"), encoding="utf-8")]
    n_cond = 0
    for i, f in enumerate(facts):
        # в граф кладём только атрибуцированные факты (param != 'параметр' или есть вещество)
        if f["param"] == "параметр" and not f["substance"]:
            continue
        cond_id = f"c{i}"
        conn.execute(
            "CREATE (c:Condition {id:$id, param:$p, substance:$s, op:$op, value:$v, "
            "value2:$v2, unit:$u, quote:$q, context:$ctx, doc_id:$d, verified:true})",
            {"id": cond_id, "p": f["param"], "s": f["substance"], "op": f["op"],
             "v": f["value"], "v2": f["value2"] if f["value2"] is not None else -1.0,
             "u": f["unit"], "q": f["quote"], "ctx": f["context"][:400], "d": f["doc_id"]})
        conn.execute(
            "MATCH (p:Publication {id:$pid}), (c:Condition {id:$cid}) "
            "MERGE (p)-[:HAS_CONDITION]->(c)", {"pid": f["doc_id"], "cid": cond_id})
        mcid = subst_map.get(f["substance"].lower())
        if mcid:
            conn.execute("MATCH (c:Condition {id:$c}), (m:Material {id:$m}) MERGE (c)-[:ABOUT_M]->(m)",
                         {"c": cond_id, "m": mcid})
        pcid = param_proc.get(f["param"])
        if pcid:
            conn.execute("MATCH (c:Condition {id:$c}), (p:Process {id:$p}) MERGE (c)-[:ABOUT_P]->(p)",
                         {"c": cond_id, "p": pcid})
        n_cond += 1
    print(f"{n_cond} conditions loaded {time.time()-t0:.1f}s", flush=True)

    # --- статистика ---
    for tbl in ("Material", "Process", "Equipment", "Facility", "Publication", "Condition"):
        rows = q(conn, f"MATCH (n:{tbl}) RETURN count(n) AS c")
        print(f"  {tbl}: {rows[0]['c']}")
    for rel in ("MENTIONS", "MENTIONS_P", "MENTIONS_E", "MENTIONS_F", "HAS_CONDITION", "ABOUT_M"):
        rows = q(conn, f"MATCH ()-[r:{rel}]->() RETURN count(r) AS c")
        print(f"  {rel}: {rows[0]['c']}")
    print(f"TOTAL {time.time()-t0:.1f}s")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()

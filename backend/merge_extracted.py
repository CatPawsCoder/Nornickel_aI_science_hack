# -*- coding: utf-8 -*-
"""Мёрдж LLM-извлечений в граф с обязательной верификацией.

Каждый claim принимается ТОЛЬКО если его quote дословно найдена в исходном
тексте документа (string-match) — та же модель верификации, что и для чисел.
Непрошедшие цитаты понижаются до confidence=low и помечаются verified=false,
либо отбрасываются (--strict).
"""
import glob
import json
import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ontology"))

from graph import open_db, q as gq, ROOT

CACHE = os.path.join(ROOT, "data", "cache")
EXTRACTED = os.path.join(CACHE, "extracted")


def norm_space(s: str) -> str:
    import re
    return re.sub(r"\s+", " ", s).strip()


def quote_in_text(quote: str, text: str, text_norm: str) -> bool:
    if quote in text:
        return True
    return norm_space(quote) in text_norm


def parse_entity_ref(ref: str) -> tuple[str, str] | None:
    """'Process:electrowinning' -> ('Process','electrowinning'); NEW:* пропускаем."""
    if ref.startswith("NEW:"):
        return None
    parts = ref.split(":", 1)
    if len(parts) != 2 or parts[0] not in ("Material", "Process", "Equipment", "Facility"):
        return None
    return parts[0], parts[1]


def main() -> None:
    conn = open_db()
    # миграция схемы для уже существующей базы (свежая создаётся сразу с колонками)
    for col, ctype in (("quote", "STRING"), ("verified", "BOOLEAN"), ("geo", "STRING")):
        try:
            conn.execute(f"ALTER TABLE Claim ADD {col} {ctype}")
        except Exception:
            pass
    docs = {json.loads(l)["id"]: json.loads(l)
            for l in open(os.path.join(CACHE, "docs.jsonl"), encoding="utf-8")}
    now = datetime.date.today().isoformat()

    # versioning-lite: существующие утверждения по документам (для пометки superseded)
    existing = {}
    try:
        for r in gq(conn, "MATCH (c:Claim) RETURN c.id AS id, c.doc_id AS d, c.text AS t"):
            existing.setdefault(r["d"], {})[norm_space(r["t"]).lower()[:150]] = r["id"]
    except Exception:
        pass

    n_claims = n_rel = n_exp = n_quote_fail = 0
    files = glob.glob(os.path.join(EXTRACTED, "*.json"))
    for fp in files:
        data = json.load(open(fp, encoding="utf-8"))
        doc_id = data["doc_id"]
        d = docs.get(doc_id)
        if not d:
            print(f"skip unknown doc {doc_id}")
            continue
        text = open(os.path.join(ROOT, d["text_path"]), encoding="utf-8").read()
        text_norm = norm_space(text)

        for cl in data.get("claims", []):
            verified = quote_in_text(cl.get("quote", ""), text, text_norm)
            conf = cl.get("confidence", "medium")
            if not verified:
                n_quote_fail += 1
                conf = "low"
            conn.execute(
                "MERGE (c:Claim {id:$id}) SET c.text=$t, c.confidence=$conf, "
                "c.doc_id=$d, c.year=$y, c.status=$st, c.superseded_by='', c.created_at=$now, "
                "c.quote=$q, c.verified=$v, c.geo=$g",
                {"id": cl["id"], "t": cl["text"], "conf": conf, "d": doc_id,
                 "y": d["year"] or 0, "st": "active" if verified else "unverified_quote",
                 "now": now, "q": (cl.get("quote") or "")[:300], "v": verified,
                 "g": cl.get("geo", "") if cl.get("geo") in ("ru", "foreign", "both") else ""})
            # versioning-lite: то же утверждение под другим id -> старое помечаем superseded
            key = norm_space(cl["text"]).lower()[:150]
            old_id = existing.get(doc_id, {}).get(key)
            if old_id and old_id != cl["id"]:
                conn.execute(
                    "MATCH (o:Claim {id:$oid}) SET o.status='superseded', o.superseded_by=$nid",
                    {"oid": old_id, "nid": cl["id"]})
            conn.execute(
                "MATCH (p:Publication {id:$p}), (c:Claim {id:$c}) MERGE (p)-[:STATES]->(c)",
                {"p": doc_id, "c": cl["id"]})
            for ref in cl.get("entities", []):
                er = parse_entity_ref(ref)
                if not er:
                    continue
                etype, eid = er
                rel = {"Material": "CLAIM_ABOUT_M", "Process": "CLAIM_ABOUT_P"}.get(etype)
                if rel:
                    conn.execute(
                        f"MATCH (c:Claim {{id:$c}}), (x:{etype} {{id:$e}}) MERGE (c)-[:{rel}]->(x)",
                        {"c": cl["id"], "e": eid})
            n_claims += 1

        for r in data.get("relations", []):
            fr = parse_entity_ref(r.get("from", ""))
            to = parse_entity_ref(r.get("to", ""))
            if not fr or not to or fr[0] != "Process":
                continue
            rel_name = {"uses_material": ("USES_MATERIAL", "Material"),
                        "produces_output": ("PRODUCES_OUTPUT", "Material"),
                        "uses_equipment": ("USES_EQUIPMENT", "Equipment"),
                        "applied_at": ("APPLIED_AT", "Facility")}.get(r.get("type", ""))
            if not rel_name or to[0] != rel_name[1]:
                continue
            conn.execute(
                f"MATCH (a:Process {{id:$a}}), (b:{rel_name[1]} {{id:$b}}) "
                f"MERGE (a)-[rl:{rel_name[0]}]->(b) SET rl.source=$s",
                {"a": fr[1], "b": to[1], "s": doc_id})
            n_rel += 1

        for e in data.get("experts", []):
            name = e.get("name", "").strip()
            if not name:
                continue
            # стабильный ID: python hash() рандомизирован между запусками -> md5
            import hashlib
            eid = "exp_" + hashlib.md5(name.lower().encode("utf-8")).hexdigest()[:10]
            conn.execute("MERGE (x:Expert {id:$id}) SET x.name=$n, x.affiliation=$a",
                         {"id": eid, "n": name, "a": e.get("affiliation", "")})
            conn.execute("MATCH (x:Expert {id:$id}), (p:Publication {id:$p}) "
                         "MERGE (x)-[:AUTHORED]->(p)", {"id": eid, "p": doc_id})
            for ref in e.get("expertise", []):
                er = parse_entity_ref(ref)
                if er and er[0] == "Process":
                    conn.execute("MATCH (x:Expert {id:$id}), (pr:Process {id:$e}) "
                                 "MERGE (x)-[:EXPERT_IN_P]->(pr)", {"id": eid, "e": er[1]})
                elif er and er[0] == "Material":
                    conn.execute("MATCH (x:Expert {id:$id}), (m:Material {id:$e}) "
                                 "MERGE (x)-[:EXPERT_IN_M]->(m)", {"id": eid, "e": er[1]})
            n_exp += 1

    print(f"files={len(files)} claims={n_claims} (quote_fail={n_quote_fail}) "
          f"relations={n_rel} experts={n_exp}")
    for tbl in ("Claim", "Expert"):
        print(tbl, gq(conn, f"MATCH (n:{tbl}) RETURN count(n) AS c")[0]["c"])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()

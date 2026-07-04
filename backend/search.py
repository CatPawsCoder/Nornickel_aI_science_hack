# -*- coding: utf-8 -*-
"""Гибридный поиск: BM25 по чанкам + сущности тезауруса + числовые фильтры графа.

Парсер запроса ДЕТЕРМИНИРОВАННЫЙ:
  - числовые ограничения — той же regex-грамматикой, что и корпус (numeric.py)
  - сущности — споттинг тезауруса (RU/EN синонимы)
  - география — «отечественная/зарубежная/мировая практика»
  - годы — «за последние N лет», «с 2018», «2010-2020»
LLM на этом этапе не нужна => нулевая недетерминированность фильтров.
"""
import json
import os
import pickle
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ontology"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from numeric import extract_numeric_facts
from thesaurus import build_matcher, spot, MATERIALS, PROCESSES, EQUIPMENT, FACILITIES

CACHE = os.path.join(ROOT, "data", "cache")
INDEX_P = os.path.join(CACHE, "bm25.pkl")
FTS_P = os.path.join(CACHE, "fts.db")
# лайт-режим (VPS с малой RAM): дисковый SQLite FTS5 вместо pickle-индекса в памяти
LIGHT = os.environ.get("KLUBOK_LIGHT") == "1" or (
    not os.path.exists(INDEX_P) and os.path.exists(FTS_P))

CURRENT_YEAR = 2026

_WORD = re.compile(r"[а-яёa-z0-9]+", re.I)

# лёгкий русский стеммер: срезаем частотные окончания (для BM25 достаточно)
_SUFFIXES = ("иями", "ями", "ами", "иях", "ях", "ах", "ией", "ей", "ой", "ий",
             "ый", "ая", "яя", "ое", "ее", "ия", "ья", "ии", "ов", "ев", "ам",
             "ям", "ом", "ем", "ум", "ую", "юю", "ых", "их", "ет", "ит", "ут",
             "ют", "ат", "ят", "а", "я", "о", "е", "и", "ы", "у", "ю", "ь")

def _stem(w: str) -> str:
    if len(w) <= 4:
        return w
    for s in _SUFFIXES:
        if w.endswith(s) and len(w) - len(s) >= 4:
            return w[:-len(s)]
    return w

def tokenize(text: str) -> list[str]:
    return [_stem(w.lower()) for w in _WORD.findall(text)]


def _load_docs() -> dict:
    docs = [json.loads(l) for l in open(os.path.join(CACHE, "docs.jsonl"), encoding="utf-8")]
    return {d["id"]: d for d in docs}


def fts_query(query: str, top: int = 240) -> list[tuple[str, float, str]]:
    """Лайт-поиск: [(doc_id, score, chunk_text)] из SQLite FTS5 (bm25-ранжирование)."""
    import sqlite3
    toks = [t for t in tokenize(query) if len(t) > 1]
    if not toks:
        return []
    match = " OR ".join('"' + t.replace('"', "") + '"' for t in toks[:30])
    con = sqlite3.connect(FTS_P)
    try:
        rows = con.execute(
            "SELECT f.rowid, bm25(chunk_fts) AS s FROM chunk_fts f "
            "WHERE chunk_fts MATCH ? ORDER BY s LIMIT ?", (match, top)).fetchall()
        if not rows:
            return []
        ids = [r[0] for r in rows]
        score_of = {r[0]: -r[1] for r in rows}  # bm25(): меньше = лучше -> инвертируем
        q = f"SELECT id, doc_id, text FROM chunk WHERE id IN ({','.join('?'*len(ids))})"
        out = [(doc_id, score_of[cid], text) for cid, doc_id, text in con.execute(q, ids)]
        out.sort(key=lambda t: -t[1])
        return out
    finally:
        con.close()


def build_index() -> dict:
    from rank_bm25 import BM25Okapi
    docs = [json.loads(l) for l in open(os.path.join(CACHE, "docs.jsonl"), encoding="utf-8")]
    chunks, meta = [], []
    for d in docs:
        text = open(os.path.join(ROOT, d["text_path"]), encoding="utf-8").read()
        paras = re.split(r"\n\s*\n", text)
        buf, start = "", 0
        for p in paras:
            if len(buf) + len(p) > 1400 and buf:
                chunks.append(buf)
                meta.append({"doc_id": d["id"], "start": start})
                buf = p
            else:
                buf = (buf + "\n\n" + p) if buf else p
        if buf.strip():
            chunks.append(buf)
            meta.append({"doc_id": d["id"], "start": start})
    tokenized = [tokenize(c) for c in chunks]
    bm25 = BM25Okapi(tokenized)
    idx = {"bm25": bm25, "chunks": chunks, "meta": meta,
           "docs": {d["id"]: d for d in docs}}
    with open(INDEX_P, "wb") as f:
        pickle.dump(idx, f)
    return idx


def load_index() -> dict:
    if LIGHT:
        return {"lite": True, "docs": _load_docs()}
    if os.path.exists(INDEX_P):
        with open(INDEX_P, "rb") as f:
            return pickle.load(f)
    return build_index()


# ---------------------------------------------------------------- query parse
GEO_RU_Q = re.compile(r"отечествен|росси|в\s+россии|российск", re.I)
GEO_F_Q = re.compile(r"зарубеж|мирово[йм]\s+практик|за\s+рубежом|иностранн|международн", re.I)
LAST_N = re.compile(r"последни[ех]\s+(\d+)\s+лет", re.I)
SINCE_Y = re.compile(r"(?:с|после|начиная\s+с)\s+(20[0-2]\d|19[89]\d)\s*(?:года|г\.)?", re.I)
RANGE_Y = re.compile(r"(20[0-2]\d|19[89]\d)\s*[-–—]\s*(20[0-2]\d|19[89]\d)")

_matchers = None

def parse_query(query: str) -> dict:
    global _matchers
    if _matchers is None:
        _matchers = build_matcher()
    numeric = [f.to_dict() for f in extract_numeric_facts(query)]
    ents = spot(query, _matchers)
    geo = None
    has_ru = bool(GEO_RU_Q.search(query))
    has_f = bool(GEO_F_Q.search(query))
    if has_ru and has_f:
        geo = "compare"          # сравнительный запрос: РФ vs мир
    elif has_ru:
        geo = "ru"
    elif has_f:
        geo = "foreign"
    year_from = year_to = None
    m = LAST_N.search(query)
    if m:
        year_from = CURRENT_YEAR - int(m.group(1))
    m = SINCE_Y.search(query)
    if m:
        year_from = int(m.group(1))
    m = RANGE_Y.search(query)
    if m:
        year_from, year_to = int(m.group(1)), int(m.group(2))
    return {
        "text": query,
        "entities": [{"type": t, "id": c, "count": n} for (t, c), n in
                     sorted(ents.items(), key=lambda kv: -kv[1])],
        "numeric": numeric,
        "geo": geo,
        "year_from": year_from,
        "year_to": year_to,
    }


# ---------------------------------------------------------------- filters
def _cond_matches(cond: dict, want: dict) -> bool:
    """Пересекается ли условие из графа с ограничением из запроса.
    Сравниваем только при совпадении единиц (после нормализации дм3/л)."""
    UNIT_EQ = {"мг/дм3": "мг/л", "мг/дм³": "мг/л", "г/дм3": "г/л", "г/дм³": "г/л",
               "°c": "°с", "ос": "°с", "а/м²": "а/м2", "м³/ч": "м3/ч"}
    u1 = UNIT_EQ.get(cond["unit"].lower(), cond["unit"].lower())
    u2 = UNIT_EQ.get(want["unit"].lower(), want["unit"].lower())
    if u1 != u2:
        return False
    lo1, hi1 = _bounds(cond)
    lo2, hi2 = _bounds(want)
    return lo1 <= hi2 and lo2 <= hi1


def _bounds(f: dict) -> tuple[float, float]:
    INF = float("inf")
    v, v2, op = f["value"], f.get("value2"), f["op"]
    if op == "range" and v2 is not None:
        return v, v2
    if op in ("<=", "<"):
        return 0.0, v
    if op in (">=", ">"):
        return v, INF
    if op == "~":
        return v * 0.8, v * 1.2
    return v, v


def name_of(etype: str, cid: str) -> str:
    src = {"Material": MATERIALS, "Process": PROCESSES,
           "Equipment": EQUIPMENT, "Facility": FACILITIES}[etype]
    return src.get(cid, {}).get("name", cid)


# ---------------------------------------------------------------- search
def search(query: str, idx: dict, conn=None, top_chunks: int = 12) -> dict:
    from graph import q as gq
    parsed = parse_query(query)
    docs = idx["docs"]

    # 1-2. кандидаты-публикации: BM25 по чанкам (in-RAM или FTS5) + бонус за сущности
    doc_score: dict[str, float] = {}
    doc_chunk_texts: dict[str, list[str]] = {}
    if idx.get("lite"):
        for did, score, text in fts_query(query):
            if did not in doc_score:
                doc_score[did] = score
                doc_chunk_texts[did] = []
            if len(doc_chunk_texts[did]) < 3:
                doc_chunk_texts[did].append(text)
    else:
        scores = idx["bm25"].get_scores(tokenize(query))
        order = sorted(range(len(scores)), key=lambda i: -scores[i])
        for i in order[:200]:
            did = idx["meta"][i]["doc_id"]
            if scores[i] <= 0:
                break
            if did not in doc_score:
                doc_score[did] = float(scores[i])
                doc_chunk_texts[did] = []
            if len(doc_chunk_texts[did]) < 3:
                doc_chunk_texts[did].append(idx["chunks"][i])

    ent_docs = {}
    if conn is not None and parsed["entities"]:
        rel_of = {"Material": "MENTIONS", "Process": "MENTIONS_P",
                  "Equipment": "MENTIONS_E", "Facility": "MENTIONS_F"}
        for e in parsed["entities"]:
            rows = gq(conn,
                f"MATCH (p:Publication)-[r:{rel_of[e['type']]}]->(x:{e['type']} {{id:$id}}) "
                f"RETURN p.id AS id, r.count AS cnt", {"id": e["id"]})
            for r in rows:
                ent_docs.setdefault(r["id"], 0)
                ent_docs[r["id"]] += min(r["cnt"], 20)
    for did, bonus in ent_docs.items():
        doc_score[did] = doc_score.get(did, 0.0) + 0.5 * bonus

    # 3. фильтры: гео, годы
    def passes(did: str) -> bool:
        d = docs.get(did)
        if d is None:
            return False
        if parsed["geo"] in ("ru", "foreign") and d["geo_hint"] not in (parsed["geo"], "mixed"):
            return False
        if parsed["year_from"] and d["year"] and d["year"] < parsed["year_from"]:
            return False
        if parsed["year_to"] and d["year"] and d["year"] > parsed["year_to"]:
            return False
        return True

    ranked = [did for did in sorted(doc_score, key=lambda k: -doc_score[k]) if passes(did)]

    # 4. числовые условия из графа, пересекающиеся с ограничениями запроса
    matched_conditions = []
    if conn is not None and parsed["numeric"]:
        for want in parsed["numeric"]:
            params_to_try = want.get("all_params") or [want["param"]]
            seen_ids = set()
            for param_name in params_to_try:
                rows = gq(conn,
                    "MATCH (p:Publication)-[:HAS_CONDITION]->(c:Condition) "
                    "WHERE c.param = $param "
                    "RETURN c.id AS id, c.param AS param, c.substance AS substance, "
                    "c.op AS op, c.value AS value, c.value2 AS value2, c.unit AS unit, "
                    "c.quote AS quote, c.context AS context, p.id AS doc_id, p.title AS title "
                    "LIMIT 500", {"param": param_name})
                for r in rows:
                    if r["id"] in seen_ids:
                        continue
                    r2 = dict(r)
                    r2["value2"] = None if r2["value2"] == -1.0 else r2["value2"]
                    if _cond_matches(r2, want) and passes(r2["doc_id"]):
                        seen_ids.add(r["id"])
                        r2["query_constraint"] = f"{want['param']} {want['op']} {want['value']}{'-' + str(want['value2']) if want.get('value2') else ''} {want['unit']}"
                        matched_conditions.append(r2)

    # 5. claims из LLM-слоя по сущностям запроса,
    #    ранжирование по лексической близости к тексту вопроса
    claims = []
    if conn is not None and parsed["entities"]:
        seen = set()
        for e in parsed["entities"][:6]:
            rel = {"Material": "CLAIM_ABOUT_M", "Process": "CLAIM_ABOUT_P"}.get(e["type"])
            if not rel:
                continue
            rows = gq(conn,
                f"MATCH (pub:Publication)-[:STATES]->(cl:Claim)-[:{rel}]->(x:{e['type']} {{id:$id}}) "
                f"RETURN cl.id AS id, cl.text AS text, cl.confidence AS confidence, "
                f"cl.doc_id AS doc_id, cl.year AS year, pub.title AS title, pub.geo AS geo "
                f"LIMIT 100", {"id": e["id"]})
            for r in rows:
                if r["id"] not in seen and passes(r["doc_id"]):
                    seen.add(r["id"])
                    claims.append(dict(r))
        # скоринг: пересечение стем-токенов вопроса и текста утверждения;
        # редкие слова (имена фабрик, процессов) весят больше частых
        qtok = [t for t in set(tokenize(query)) if len(t) > 2]
        for c in claims:
            ctok = set(tokenize(c["text"]))
            score = sum(min(len(t), 10) for t in qtok if t in ctok)
            c["relevance"] = score
        claims.sort(key=lambda c: -c["relevance"])

    top_chunk_texts = []
    for did in ranked[:6]:
        for text in doc_chunk_texts.get(did, [])[:2]:
            top_chunk_texts.append({"doc_id": did, "text": text[:1500]})

    return {
        "parsed": parsed,
        "publications": [
            {**{k: docs[did][k] for k in ("id", "title", "year", "lang", "geo_hint", "filename")},
             "score": round(doc_score[did], 2)} for did in ranked[:15]],
        "conditions": matched_conditions[:40],
        "claims": claims[:60],
        "chunks": top_chunk_texts[:top_chunks],
    }


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    idx = build_index()
    print("chunks:", len(idx["chunks"]))
    p = parse_query("Какие методы обессоливания воды подходят, если сульфаты 200-300 мг/л, "
                    "а требуемый сухой остаток ≤1000 мг/дм³? Отечественная практика за последние 10 лет")
    print(json.dumps(p, ensure_ascii=False, indent=1)[:1200])

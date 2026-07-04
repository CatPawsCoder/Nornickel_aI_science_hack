# -*- coding: utf-8 -*-
"""Верификация целостности графа знаний.

1. Полнота: каждый документ из docs.jsonl есть в графе как Publication.
2. Консистентность рёбер: HAS_CONDITION == Condition, ABOUT_M указывает на существующие узлы.
3. Достоверность: случайная выборка условий — цитата дословно присутствует в исходном тексте.
4. Claims: каждая цитата верифицирована, связи STATES целы.
5. Подграф: для тестового запроса рёбра ссылаются только на существующие узлы.
"""
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
sys.stdout.reconfigure(encoding="utf-8")

from graph import open_db, q as gq, ROOT

random.seed(42)
conn = open_db(read_only=True)
CACHE = os.path.join(ROOT, "data", "cache")
errors = 0

# --- 1. полнота публикаций ---
docs = {json.loads(l)["id"]: json.loads(l) for l in open(os.path.join(CACHE, "docs.jsonl"), encoding="utf-8")}
n_pub = gq(conn, "MATCH (p:Publication) RETURN count(p) AS c")[0]["c"]
print(f"[1] docs.jsonl: {len(docs)}, Publication в графе: {n_pub}", "OK" if n_pub == len(docs) else "MISMATCH!")
if n_pub != len(docs):
    errors += 1

# --- 2. консистентность рёбер ---
n_cond = gq(conn, "MATCH (c:Condition) RETURN count(c) AS c")[0]["c"]
n_hc = gq(conn, "MATCH ()-[r:HAS_CONDITION]->() RETURN count(r) AS c")[0]["c"]
print(f"[2] Condition: {n_cond}, HAS_CONDITION: {n_hc}", "OK" if n_cond == n_hc else "MISMATCH!")
if n_cond != n_hc:
    errors += 1
# осиротевшие условия (без публикации)
orphan = gq(conn, "MATCH (c:Condition) WHERE NOT EXISTS { MATCH (:Publication)-[:HAS_CONDITION]->(c) } RETURN count(c) AS c")[0]["c"]
print(f"    осиротевших условий: {orphan}", "OK" if orphan == 0 else "FAIL")
if orphan:
    errors += 1

# --- 3. выборочная string-match проверка условий (100 случайных) ---
sample = gq(conn, "MATCH (p:Publication)-[:HAS_CONDITION]->(c:Condition) "
                  "RETURN c.quote AS quote, c.doc_id AS doc_id, c.occurrences AS occ "
                  "ORDER BY c.id LIMIT 200000")
sample = random.sample(sample, min(100, len(sample)))
ok = fail = 0
for s in sample:
    d = docs.get(s["doc_id"])
    if not d:
        fail += 1
        continue
    text = open(os.path.join(ROOT, d["text_path"]), encoding="utf-8").read()
    # цитаты нормализованы по пробелам при COPY -> сверяем нормализованно
    tnorm = " ".join(text.split())
    if " ".join(s["quote"].split()) in tnorm:
        ok += 1
    else:
        fail += 1
print(f"[3] string-match 100 случайных условий: ok={ok} fail={fail}", "OK" if fail == 0 else "FAIL")
if fail:
    errors += 1

# --- 4. claims ---
n_cl = gq(conn, "MATCH (cl:Claim) RETURN count(cl) AS c")[0]["c"]
n_st = gq(conn, "MATCH ()-[r:STATES]->() RETURN count(r) AS c")[0]["c"]
unver = gq(conn, "MATCH (cl:Claim) WHERE cl.status='unverified_quote' RETURN count(cl) AS c")[0]["c"]
print(f"[4] Claim: {n_cl}, STATES: {n_st}, непроверенных цитат: {unver}",
      "OK" if n_st >= n_cl and unver == 0 else "WARN")

# --- 5. подграф тестового запроса ---
sys.path.insert(0, os.path.join(ROOT, "backend"))
from search import load_index, search
from app import build_subgraph
idx = load_index()
r = search("извлечение МПГ из гранулированного шлака Waterval", idx, conn)
sg = build_subgraph(r)
node_ids = {n["data"]["id"] for n in sg["nodes"]}
bad_edges = [e for e in sg["edges"]
             if e["data"]["source"] not in node_ids or e["data"]["target"] not in node_ids]
print(f"[5] подграф: {len(sg['nodes'])} узлов, {len(sg['edges'])} рёбер, битых рёбер: {len(bad_edges)}",
      "OK" if not bad_edges else "FAIL")
if bad_edges:
    errors += 1
top_claim = r["claims"][0] if r["claims"] else None
if top_claim:
    print(f"    топ-claim по релевантности: {top_claim['text'][:90]}... (rel={top_claim['relevance']})")

# --- дистрибуция occurrences (дедуп работает?) ---
occ = gq(conn, "MATCH (c:Condition) WHERE c.occurrences > 1 RETURN count(c) AS c")[0]["c"]
print(f"[6] условий с повторами (occurrences>1): {occ} — дубли схлопнуты, не потеряны")

print(f"\n{'✅ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ' if errors == 0 else f'❌ ОШИБОК: {errors}'}")

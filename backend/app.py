# -*- coding: utf-8 -*-
"""FastAPI-приложение «Научный клубок» — карта знаний R&D.

Эндпоинты:
  POST /api/query    — запрос на естественном языке -> структурированный ответ + подграф
  GET  /api/graph    — обзорный подграф (для стартового экрана)
  GET  /api/doc/{id} — карточка публикации
  GET  /api/stats    — метрики покрытия (дашборд руководителя)
  POST /api/monitor  — поиск новых публикаций по теме (Yandex Search API)
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from graph import open_db, q as gq, ROOT
from search import load_index, search, name_of, parse_query
from answer import synthesize
import llm

app = FastAPI(title="Научный клубок — карта знаний R&D")

# ------------------------- аудит действий (требование ИБ из ТЗ) ---------------
import datetime
import time as _time

from fastapi import Request

AUDIT_LOG = os.path.join(ROOT, "data", "audit.log")


# простейший rate-limit: публичное демо не должно позволять выжигать LLM-квоты
_RL: dict = {}
_RL_MAX_PER_MIN = 15


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path in ("/api/query", "/api/monitor", "/api/export"):
        ip = request.client.host if request.client else "?"
        now = _time.time()
        bucket = [t for t in _RL.get(ip, []) if now - t < 60]
        if len(bucket) >= _RL_MAX_PER_MIN:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "слишком много запросов, подождите минуту"},
                                status_code=429)
        bucket.append(now)
        _RL[ip] = bucket
    return await call_next(request)


@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    t0 = _time.time()
    body_preview = ""
    if request.method == "POST" and request.url.path.startswith("/api/"):
        body = await request.body()
        body_preview = body.decode("utf-8", "ignore")[:200]
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        try:
            rec = {
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "ip": request.client.host if request.client else "?",
                "method": request.method,
                "path": request.url.path,
                "query": body_preview,
                "status": response.status_code,
                "ms": round((_time.time() - t0) * 1000),
            }
            with open(AUDIT_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass  # аудит не должен ломать основную функциональность
    return response


@app.get("/api/audit")
def api_audit(request: Request, limit: int = 50):
    """Записи аудита — только для роли администратора (токен в env KLUBOK_ADMIN_TOKEN).
    Без настроенного токена endpoint выключен: лог содержит IP и тексты запросов."""
    admin_token = os.environ.get("KLUBOK_ADMIN_TOKEN", "")
    provided = request.headers.get("X-Admin-Token", "")
    if not admin_token or provided != admin_token:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "forbidden: требуется X-Admin-Token администратора"},
                            status_code=403)
    if not os.path.exists(AUDIT_LOG):
        return {"records": []}
    lines = open(AUDIT_LOG, encoding="utf-8").read().strip().splitlines()
    return {"records": [json.loads(l) for l in lines[-limit:]]}

conn = open_db(read_only=True)
idx = load_index()
DOCS = idx["docs"]

FRONT = os.path.join(ROOT, "frontend")


class Query(BaseModel):
    text: str
    geo: str | None = None       # доп. фильтр из UI
    year_from: int | None = None
    confidence: str | None = None


@app.post("/api/query")
def api_query(body: Query):
    text = body.text
    result = search(text, idx, conn)

    # UI-фильтры применяются КО ВСЕМ слоям ответа: публикации, утверждения, условия
    def doc_passes(doc_id: str) -> bool:
        d = DOCS.get(doc_id)
        if d is None:
            return False
        if body.geo in ("ru", "foreign") and d["geo_hint"] not in (body.geo, "mixed"):
            return False
        if body.year_from and d["year"] and d["year"] < body.year_from:
            return False
        return True

    if body.geo in ("ru", "foreign") or body.year_from:
        result["publications"] = [p for p in result["publications"] if doc_passes(p["id"])]
        result["claims"] = [c for c in result["claims"] if doc_passes(c["doc_id"])]
        result["conditions"] = [c for c in result["conditions"] if doc_passes(c["doc_id"])]
        # пересчёт строгого AND: после фильтра часть документов могла выпасть
        if result.get("n_constraints", 0) >= 2:
            by_constraint: dict = {}
            for c in result["conditions"]:
                by_constraint.setdefault(c.get("query_constraint", "?"), set()).add(c["doc_id"])
            if len(by_constraint) >= result["n_constraints"]:
                strict = set.intersection(*by_constraint.values())
            else:
                strict = set()   # какое-то условие целиком отфильтровано
            result["strict_docs"] = sorted(strict)
            for p in result["publications"]:
                p["strict_match"] = p["id"] in strict
    if body.confidence:
        order = {"high": 3, "medium": 2, "low": 1}
        need = order.get(body.confidence, 1)
        result["claims"] = [c for c in result["claims"]
                            if order.get(c.get("confidence", "medium"), 2) >= need]
    ans = synthesize(result, DOCS)
    subgraph = build_subgraph(result)
    return {"answer": ans, "result": {k: v for k, v in result.items() if k != "chunks"},
            "graph": subgraph}


def build_subgraph(result: dict) -> dict:
    """Подграф для cytoscape: запрос-сущности + публикации + условия + claims."""
    nodes, edges, seen = [], [], set()

    def add_node(nid, label, ntype, **extra):
        if nid in seen:
            return
        seen.add(nid)
        nodes.append({"data": {"id": nid, "label": label[:60], "type": ntype, **extra}})

    def add_edge(a, b, label=""):
        eid = f"{a}->{b}:{label}"
        if eid in seen or a not in seen or b not in seen:
            return
        seen.add(eid)
        edges.append({"data": {"id": eid, "source": a, "target": b, "label": label}})

    p = result["parsed"]
    for e in p["entities"][:8]:
        add_node(f"{e['type']}:{e['id']}", name_of(e["type"], e["id"]), e["type"].lower())
    for pub in result["publications"][:10]:
        add_node(f"Pub:{pub['id']}", pub["title"], "publication",
                 year=pub["year"], geo=pub["geo_hint"], doc_id=pub["id"])
        for e in p["entities"][:8]:
            rel_of = {"Material": "MENTIONS", "Process": "MENTIONS_P",
                      "Equipment": "MENTIONS_E", "Facility": "MENTIONS_F"}
            rows = gq(conn,
                f"MATCH (pp:Publication {{id:$pid}})-[r:{rel_of[e['type']]}]->(x:{e['type']} {{id:$eid}}) "
                f"RETURN r.count AS c", {"pid": pub["id"], "eid": e["id"]})
            if rows:
                add_edge(f"Pub:{pub['id']}", f"{e['type']}:{e['id']}", "упоминает")
    cond_node_ids = {}
    for c in result["conditions"][:15]:
        cid = f"Cond:{c['id']}"
        cond_node_ids[c["id"]] = cid
        add_node(cid, f"{c['param']} {c['op']} {c['value']:g} {c['unit']}", "condition",
                 quote=c["quote"], doc_id=c["doc_id"])
        add_edge(f"Pub:{c['doc_id']}", cid, "условие") if f"Pub:{c['doc_id']}" in seen else None
    # красные рёбра противоречий между показанными условиями
    if cond_node_ids:
        ids = list(cond_node_ids.keys())
        rows = gq(conn,
            "MATCH (a:Condition)-[r:CONTRADICTS_C]->(b:Condition) "
            "WHERE a.id IN $ids AND b.id IN $ids "
            "RETURN a.id AS a, b.id AS b, r.reason AS reason LIMIT 20", {"ids": ids})
        for r in rows:
            eid = f"contra:{r['a']}:{r['b']}"
            if eid not in seen:
                seen.add(eid)
                edges.append({"data": {"id": eid, "source": cond_node_ids[r["a"]],
                                       "target": cond_node_ids[r["b"]],
                                       "label": "противоречит", "kind": "contradicts"}})
    for cl in result["claims"][:20]:
        nid = f"Claim:{cl['id']}"
        add_node(nid, cl["text"][:60], "claim", confidence=cl.get("confidence", ""),
                 doc_id=cl["doc_id"], quote=cl.get("quote", ""))
        if f"Pub:{cl['doc_id']}" in seen:
            add_edge(f"Pub:{cl['doc_id']}", nid, "утверждает")
    # эксперты по теме — требование ТЗ «показ связанных экспертов»
    for ex in (result.get("experts") or [])[:6]:
        nid = f"Expert:{ex['id']}"
        add_node(nid, ex["name"], "expert", quote=ex.get("aff", ""))
        for e in p["entities"][:4]:
            eid = f"{e['type']}:{e['id']}"
            if eid in seen:
                add_edge(nid, eid, "эксперт в")
                break
    return {"nodes": nodes, "edges": edges}


@app.get("/api/export")
def api_export(text: str, format: str = "jsonld"):
    """Экспорт результата запроса в JSON-LD (FAIR: Interoperable/Reusable)."""
    result = search(text, idx, conn)
    graph_items = []
    for c in result["claims"][:30]:
        graph_items.append({
            "@type": "Claim",
            "@id": f"urn:klubok:claim:{c['id']}",
            "text": c["text"],
            "confidenceLevel": c.get("confidence"),
            "quotation": c.get("quote", ""),
            "datePublished": c.get("year"),
            "isBasedOn": {"@type": "CreativeWork", "name": c["title"],
                          "identifier": c["doc_id"]},
        })
    for c in result["conditions"][:30]:
        graph_items.append({
            "@type": "QuantitativeValue",
            "@id": f"urn:klubok:condition:{c['id']}",
            "name": c["param"],
            "value": c["value"],
            "unitText": c["unit"],
            "additionalProperty": c["op"],
            "quotation": c["quote"],
            "isBasedOn": {"@type": "CreativeWork", "identifier": c["doc_id"]},
        })
    return {
        "@context": {"@vocab": "https://schema.org/",
                     "confidenceLevel": "https://klubok.example/confidence",
                     "quotation": "https://schema.org/text"},
        "@type": "Dataset",
        "name": f"Научный клубок: выгрузка по запросу «{text[:100]}»",
        "query": text,
        "@graph": graph_items,
    }


@app.get("/api/graph")
def api_overview():
    """Стартовый обзор: топ сущностей по числу упоминаний."""
    nodes, edges = [], []
    rows = gq(conn, "MATCH (p:Publication)-[r:MENTIONS_P]->(x:Process) "
                    "RETURN x.id AS id, x.name AS name, count(p) AS pubs, sum(r.count) AS total "
                    "ORDER BY total DESC LIMIT 12")
    for r in rows:
        nodes.append({"data": {"id": f"Process:{r['id']}", "label": r["name"],
                               "type": "process", "weight": r["pubs"]}})
    rows2 = gq(conn, "MATCH (p:Publication)-[r:MENTIONS]->(x:Material) "
                     "RETURN x.id AS id, x.name AS name, count(p) AS pubs, sum(r.count) AS total "
                     "ORDER BY total DESC LIMIT 12")
    for r in rows2:
        nodes.append({"data": {"id": f"Material:{r['id']}", "label": r["name"],
                               "type": "material", "weight": r["pubs"]}})
    # рёбра совместных упоминаний процесс-материал
    rows3 = gq(conn,
        "MATCH (m:Material)<-[:MENTIONS]-(p:Publication)-[:MENTIONS_P]->(pr:Process) "
        "RETURN pr.id AS pid, m.id AS mid, count(p) AS n ORDER BY n DESC LIMIT 40")
    ids = {n["data"]["id"] for n in nodes}
    for r in rows3:
        a, b = f"Process:{r['pid']}", f"Material:{r['mid']}"
        if a in ids and b in ids and r["n"] >= 3:
            edges.append({"data": {"id": f"{a}-{b}", "source": a, "target": b,
                                   "label": str(r["n"])}})
    return {"nodes": nodes, "edges": edges}


@app.get("/api/doc/{doc_id}")
def api_doc(doc_id: str):
    d = DOCS.get(doc_id)
    if not d:
        return {"error": "not found"}
    conds = gq(conn, "MATCH (p:Publication {id:$id})-[:HAS_CONDITION]->(c:Condition) "
                     "RETURN c.param AS param, c.op AS op, c.value AS value, c.unit AS unit, "
                     "c.quote AS quote LIMIT 30", {"id": doc_id})
    claims = gq(conn, "MATCH (p:Publication {id:$id})-[:STATES]->(cl:Claim) "
                      "RETURN cl.text AS text, cl.confidence AS confidence LIMIT 30",
                {"id": doc_id})
    return {"doc": d, "conditions": conds, "claims": claims}


@app.get("/api/stats")
def api_stats():
    out = {}
    for tbl in ("Publication", "Material", "Process", "Equipment", "Facility",
                "Condition", "Claim", "Expert"):
        out[tbl] = gq(conn, f"MATCH (n:{tbl}) RETURN count(n) AS c")[0]["c"]
    out["llm_available"] = llm.any_llm_available()
    out["llm_provider"] = llm.active_provider()
    domains = gq(conn, "MATCH (p:Publication)-[:MENTIONS_P]->(x:Process) "
                       "RETURN x.domain AS d, count(DISTINCT p) AS pubs ORDER BY pubs DESC")
    out["coverage_by_domain"] = domains
    # гео-статистика из графа (источник истины), а не из файлового индекса
    out["geo"] = {r["g"]: r["c"] for r in
                  gq(conn, "MATCH (p:Publication) RETURN p.geo AS g, count(p) AS c")}
    out["docs_in_index"] = len(DOCS)
    return out


class MonitorQ(BaseModel):
    topic: str


@app.post("/api/monitor")
def api_monitor(body: MonitorQ, request: Request):
    # внешний поиск расходует квоты Search API — ограничиваем длину темы
    topic = (body.topic or "").strip()[:120]
    if len(topic) < 4:
        return {"topic": topic, "found": [], "error": "тема слишком короткая"}
    items = llm.search_web(topic + " металлургия исследование")
    return {"topic": topic, "found": items}


@app.get("/")
def index():
    return FileResponse(os.path.join(FRONT, "index.html"))

app.mount("/static", StaticFiles(directory=FRONT), name="static")

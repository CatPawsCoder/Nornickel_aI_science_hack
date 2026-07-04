# -*- coding: utf-8 -*-
"""Материализация рёбер CONTRADICTS_C: конфликтующие числовые условия.

Конфликт = два условия из РАЗНЫХ документов с одинаковыми (параметр, вещество,
единица), чьи числовые интервалы НЕ пересекаются и различаются существенно
(>2x по центру интервала — отсекает тривиальные вариации режимов).

Результат виден в графе как красные рёбра «источники расходятся» и
используется в секции «Зоны разногласий».
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from graph import open_db, q as gq

INF = float("inf")


def bounds(op, v, v2):
    if op == "range" and v2 is not None and v2 != -1.0:
        return v, v2
    if op in ("<=", "<"):
        return 0.0, v
    if op in (">=", ">"):
        return v, INF
    if op == "~":
        return v * 0.8, v * 1.2
    return v, v


def center(lo, hi):
    if hi == INF:
        return lo * 2 if lo else 1.0
    return (lo + hi) / 2 or 1e-9


def main(max_pairs_per_group: int = 6, max_total: int = 3000):
    conn = open_db()
    rows = gq(conn,
        "MATCH (c:Condition) WHERE c.param <> 'параметр' AND c.substance <> '' "
        "RETURN c.id AS id, c.param AS param, c.substance AS substance, c.op AS op, "
        "c.value AS v, c.value2 AS v2, c.unit AS unit, c.doc_id AS doc")
    groups = defaultdict(list)
    for r in rows:
        key = (r["param"], r["substance"].lower(), r["unit"].lower())
        groups[key].append(r)

    n_edges = 0
    for (param, subst, unit), items in groups.items():
        if len(items) < 2 or len(items) > 400:
            continue
        # интервалы
        bs = [(bounds(i["op"], i["v"], i["v2"]), i) for i in items]
        pairs = 0
        for i in range(len(bs)):
            if pairs >= max_pairs_per_group or n_edges >= max_total:
                break
            (lo1, hi1), a = bs[i]
            for j in range(i + 1, len(bs)):
                (lo2, hi2), b = bs[j]
                if a["doc"] == b["doc"]:
                    continue
                disjoint = hi1 < lo2 or hi2 < lo1
                if not disjoint:
                    continue
                c1, c2 = center(lo1, hi1), center(lo2, hi2)
                if max(c1, c2) / max(min(c1, c2), 1e-9) < 2.0:
                    continue  # различие несущественное
                reason = f"{param}/{subst}: {a['op']} {a['v']:g} vs {b['op']} {b['v']:g} {unit}"
                conn.execute(
                    "MATCH (x:Condition {id:$a}), (y:Condition {id:$b}) "
                    "MERGE (x)-[r:CONTRADICTS_C]->(y) SET r.reason=$rs",
                    {"a": a["id"], "b": b["id"], "rs": reason[:200]})
                n_edges += 1
                pairs += 1
                if pairs >= max_pairs_per_group or n_edges >= max_total:
                    break
    total = gq(conn, "MATCH ()-[r:CONTRADICTS_C]->() RETURN count(r) AS c")[0]["c"]
    print(f"CONTRADICTS_C edges: +{n_edges} (всего {total})")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()

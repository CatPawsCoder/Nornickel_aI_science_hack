# -*- coding: utf-8 -*-
"""Граф знаний на Kùzu (embedded, Cypher).

Схема онтологии:
  Узлы:  Material, Process, Equipment, Facility, Publication,
         Condition (числовой факт), Claim (вывод/утверждение), Expert
  Рёбра: MENTIONS (Publication->сущность, с частотой),
         HAS_CONDITION (Publication->Condition),
         ABOUT (Condition->Material/Process — привязка по контексту),
         USES_MATERIAL, PRODUCES_OUTPUT, USES_EQUIPMENT (Process->...),
         STATES (Publication->Claim), SUPPORTS/CONTRADICTS (Claim<->Claim),
         EXPERT_IN (Expert->Process|Material), AUTHORED (Expert->Publication),
         APPLIED_AT (Process->Facility)

Версионирование: у Claim есть status/superseded_by, у всех фактов created_at и doc-источник.
"""
import json
import os
import shutil

import kuzu

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "kg.kuzu")

SCHEMA = [
    # --- узлы ---
    """CREATE NODE TABLE IF NOT EXISTS Material(
        id STRING, name STRING, name_en STRING, kind STRING, PRIMARY KEY(id))""",
    """CREATE NODE TABLE IF NOT EXISTS Process(
        id STRING, name STRING, name_en STRING, domain STRING, PRIMARY KEY(id))""",
    """CREATE NODE TABLE IF NOT EXISTS Equipment(
        id STRING, name STRING, name_en STRING, PRIMARY KEY(id))""",
    """CREATE NODE TABLE IF NOT EXISTS Facility(
        id STRING, name STRING, geo STRING, PRIMARY KEY(id))""",
    """CREATE NODE TABLE IF NOT EXISTS Publication(
        id STRING, title STRING, year INT64, lang STRING, geo STRING,
        source_type STRING, credibility STRING, filename STRING, PRIMARY KEY(id))""",
    """CREATE NODE TABLE IF NOT EXISTS Condition(
        id STRING, param STRING, substance STRING, op STRING,
        value DOUBLE, value2 DOUBLE, unit STRING, quote STRING,
        context STRING, doc_id STRING, verified BOOLEAN,
        occurrences INT64, PRIMARY KEY(id))""",
    """CREATE NODE TABLE IF NOT EXISTS Claim(
        id STRING, text STRING, confidence STRING, doc_id STRING, year INT64,
        status STRING, superseded_by STRING, created_at STRING,
        quote STRING, verified BOOLEAN, geo STRING, PRIMARY KEY(id))""",
    """CREATE NODE TABLE IF NOT EXISTS Expert(
        id STRING, name STRING, affiliation STRING, PRIMARY KEY(id))""",
    # --- рёбра ---
    "CREATE REL TABLE IF NOT EXISTS MENTIONS(FROM Publication TO Material, count INT64)",
    "CREATE REL TABLE IF NOT EXISTS MENTIONS_P(FROM Publication TO Process, count INT64)",
    "CREATE REL TABLE IF NOT EXISTS MENTIONS_E(FROM Publication TO Equipment, count INT64)",
    "CREATE REL TABLE IF NOT EXISTS MENTIONS_F(FROM Publication TO Facility, count INT64)",
    "CREATE REL TABLE IF NOT EXISTS HAS_CONDITION(FROM Publication TO Condition)",
    "CREATE REL TABLE IF NOT EXISTS ABOUT_M(FROM Condition TO Material)",
    "CREATE REL TABLE IF NOT EXISTS ABOUT_P(FROM Condition TO Process)",
    "CREATE REL TABLE IF NOT EXISTS USES_MATERIAL(FROM Process TO Material, source STRING)",
    "CREATE REL TABLE IF NOT EXISTS PRODUCES_OUTPUT(FROM Process TO Material, source STRING)",
    "CREATE REL TABLE IF NOT EXISTS USES_EQUIPMENT(FROM Process TO Equipment, source STRING)",
    "CREATE REL TABLE IF NOT EXISTS STATES(FROM Publication TO Claim)",
    "CREATE REL TABLE IF NOT EXISTS CLAIM_ABOUT_P(FROM Claim TO Process)",
    "CREATE REL TABLE IF NOT EXISTS CLAIM_ABOUT_M(FROM Claim TO Material)",
    "CREATE REL TABLE IF NOT EXISTS SUPPORTS(FROM Claim TO Claim)",
    "CREATE REL TABLE IF NOT EXISTS CONTRADICTS(FROM Claim TO Claim, reason STRING)",
    "CREATE REL TABLE IF NOT EXISTS CONTRADICTS_C(FROM Condition TO Condition, reason STRING)",
    "CREATE REL TABLE IF NOT EXISTS EXPERT_IN_P(FROM Expert TO Process)",
    "CREATE REL TABLE IF NOT EXISTS EXPERT_IN_M(FROM Expert TO Material)",
    "CREATE REL TABLE IF NOT EXISTS AUTHORED(FROM Expert TO Publication)",
    "CREATE REL TABLE IF NOT EXISTS APPLIED_AT(FROM Process TO Facility, source STRING)",
]


def open_db(fresh: bool = False, read_only: bool = False) -> kuzu.Connection:
    if fresh and os.path.exists(DB_PATH):
        shutil.rmtree(DB_PATH, ignore_errors=True)
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
    kw = {}
    buf_mb = os.environ.get("KUZU_BUFFER_MB")
    if buf_mb:
        kw["buffer_pool_size"] = int(buf_mb) * 1024 * 1024
    db = kuzu.Database(DB_PATH, read_only=read_only, **kw)
    conn = kuzu.Connection(db)
    if not read_only:
        for stmt in SCHEMA:
            conn.execute(stmt)
    return conn


def q(conn: kuzu.Connection, cypher: str, params: dict | None = None):
    res = conn.execute(cypher, parameters=params or {})
    cols = res.get_column_names()
    rows = []
    while res.has_next():
        rows.append(dict(zip(cols, res.get_next())))
    return rows

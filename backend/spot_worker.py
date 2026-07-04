# -*- coding: utf-8 -*-
"""Воркер multiprocessing: споттинг сущностей + числовые факты для одного документа.

Инициализируется один раз на процесс (compile матчеров), затем обрабатывает doc-задачи.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ontology"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from thesaurus import build_matcher, spot, MATERIALS
from numeric import extract_numeric_facts, validate_fact

SPOT_LIMIT = 300_000
MAX_COND_PER_DOC = 300
PRICE_NOISE = ("prices", "quarterly", "lme", "forecast")

_matchers = None
_subst_map = None
_param_proc = {"плотность тока": "electrowinning", "выход по току": "electrowinning",
               "сухой остаток": "desalination", "крупность": "grinding"}


def _init():
    global _matchers, _subst_map
    if _matchers is None:
        _matchers = build_matcher()
        _subst_map = {}
        for cid, m in MATERIALS.items():
            for v in [m["name"], *(m.get("syn") or [])]:
                _subst_map[v.lower()] = cid


def process_doc(args):
    """args = (doc_id, filename, text_path, root). Возвращает dict с рядами для COPY."""
    _init()
    doc_id, filename, text_path, root = args
    try:
        text = open(os.path.join(root, text_path), encoding="utf-8").read()
    except Exception:
        return {"doc_id": doc_id, "mentions": [], "conds": []}
    scan_text = text[:SPOT_LIMIT]
    hits = spot(scan_text, _matchers)
    mentions = [(etype, cid, n) for (etype, cid), n in hits.items()]

    conds = []
    fn_low = filename.lower()
    if not any(k in fn_low for k in PRICE_NOISE):
        cnt = 0
        for f in extract_numeric_facts(scan_text):
            if cnt >= MAX_COND_PER_DOC:
                break
            fd = f.to_dict()
            if fd["param"] == "параметр" and not fd["substance"]:
                continue
            if fd["quote"] not in text:
                continue
            mcid = _subst_map.get(fd["substance"].lower())
            pcid = _param_proc.get(fd["param"])
            conds.append((fd["param"], fd["substance"], fd["op"], fd["value"],
                          fd["value2"] if fd["value2"] is not None else -1.0,
                          fd["unit"], fd["quote"][:200], fd["context"][:300], mcid, pcid))
            cnt += 1
    return {"doc_id": doc_id, "mentions": mentions, "conds": conds}

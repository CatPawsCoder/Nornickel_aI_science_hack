# -*- coding: utf-8 -*-
"""Воркер multiprocessing: споттинг сущностей + числовые факты для одного документа.

Метод (v2, без потери данных):
  - обрабатывается ПОЛНЫЙ текст каждого документа (без обрезки);
  - никакие файлы не пропускаются (ценовые XLS тоже обрабатываются);
  - вместо капов — дедупликация: одинаковые факты (параметр, вещество,
    оператор, значение, единица) внутри документа схлопываются в один
    с накоплением счётчика повторов (occurrences). Информация не теряется:
    уникальные значения все сохраняются, дубли не раздувают граф.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ontology"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from thesaurus import build_matcher, spot, MATERIALS
from numeric import extract_numeric_facts

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
    """args = (doc_id, filename, text_path, root).
    Возвращает mentions + уникальные числовые факты с occurrences."""
    _init()
    doc_id, filename, text_path, root = args
    try:
        text = open(os.path.join(root, text_path), encoding="utf-8").read()
    except Exception:
        return {"doc_id": doc_id, "mentions": [], "conds": [], "n_raw": 0}

    # споттинг по полному тексту
    hits = spot(text, _matchers)
    mentions = [(etype, cid, n) for (etype, cid), n in hits.items()]

    # числа по полному тексту, дедуп внутри документа
    uniq = {}   # key -> [fact_tuple, occurrences]
    n_raw = 0
    for f in extract_numeric_facts(text):
        fd = f.to_dict()
        if fd["param"] == "параметр" and not fd["substance"]:
            continue
        if fd["quote"] not in text:
            continue
        n_raw += 1
        key = (fd["param"], fd["substance"].lower(), fd["op"],
               fd["value"], fd["value2"], fd["unit"].lower())
        if key in uniq:
            uniq[key][1] += 1
            continue
        mcid = _subst_map.get(fd["substance"].lower())
        pcid = _param_proc.get(fd["param"])
        uniq[key] = [(fd["param"], fd["substance"], fd["op"], fd["value"],
                      fd["value2"] if fd["value2"] is not None else -1.0,
                      fd["unit"], fd["quote"][:200], fd["context"][:300], mcid, pcid), 1]

    conds = [(*fact, occ) for fact, occ in uniq.values()]
    return {"doc_id": doc_id, "mentions": mentions, "conds": conds, "n_raw": n_raw}

# -*- coding: utf-8 -*-
"""Автоматическая LLM-экстракция утверждений из корпуса.

Та же модель верификации, что и у ручного слоя:
  - LLM выдаёт строгий JSON (claims с дословными цитатами);
  - каждая цитата проверяется string-match к исходному тексту;
  - непрошедшие цитаты отбрасываются (в граф не попадают);
  - канонизация сущностей — по тезаурусу.

Выход: data/cache/extracted/<doc_id>.json — тот же формат, что у субагентов,
поэтому merge_extracted.py подхватывает без изменений.
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ontology"))

import llm
from thesaurus import MATERIALS, PROCESSES, EQUIPMENT, FACILITIES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "cache")
EXTRACTED = os.path.join(CACHE, "extracted")
os.makedirs(EXTRACTED, exist_ok=True)

HEAD_CHARS = 14000          # сколько текста документа отдаём LLM
MAX_DOCS = int(os.environ.get("LLM_EXTRACT_MAX_DOCS", "80"))

ENTITY_LIST = ", ".join(
    [f"Material:{k}" for k in MATERIALS] +
    [f"Process:{k}" for k in PROCESSES] +
    [f"Equipment:{k}" for k in EQUIPMENT] +
    [f"Facility:{k}" for k in FACILITIES])

SYSTEM = (
    "Ты — экстрактор знаний для графа знаний горно-металлургической отрасли. "
    "Из фрагмента документа извлеки 5-10 ключевых утверждений (методы, параметры, "
    "результаты, применимость, сравнение практик). Верни СТРОГО валидный JSON без "
    "markdown-обёртки:\n"
    '{"claims":[{"text":"чёткое утверждение", "confidence":"high|medium|low", '
    '"quote":"ДОСЛОВНАЯ цитата из текста 50-200 символов, копируй точно", '
    '"entities":["Process:...","Material:..."], "geo":"ru|foreign|both|unknown"}]}\n'
    f"Канонические ID сущностей (используй только их): {ENTITY_LIST}. "
    "Если сущности нет в списке — пропусти её. Все числа в text обязаны быть в quote. "
    "quote будет проверена автоматически на дословное совпадение."
)

_norm_re = re.compile(r"\s+")


def norm(s: str) -> str:
    return _norm_re.sub(" ", s).strip()


def parse_json(raw: str):
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.S)
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def extract_doc(d: dict) -> dict | None:
    text = open(os.path.join(ROOT, d["text_path"]), encoding="utf-8").read()
    head = text[:HEAD_CHARS]
    raw = llm.complete(SYSTEM, f"Документ: «{d['title'][:100]}» ({d['year'] or 'н/д'})\n\n{head}",
                       temperature=0.1, max_tokens=2500)
    if not raw:
        return None
    data = parse_json(raw)
    if not data or "claims" not in data:
        return None
    text_norm = norm(text)
    good = []
    for i, cl in enumerate(data["claims"], 1):
        quote = (cl.get("quote") or "").strip()
        if not quote or len(quote) < 25:
            continue
        # верификация: дословно (с нормализацией пробелов)
        if quote not in text and norm(quote) not in text_norm:
            continue  # цитата не найдена -> в граф не попадает
        ents = []
        for e in cl.get("entities", []):
            p = e.split(":", 1)
            if len(p) == 2 and p[0] in ("Material", "Process", "Equipment", "Facility"):
                src = {"Material": MATERIALS, "Process": PROCESSES,
                       "Equipment": EQUIPMENT, "Facility": FACILITIES}[p[0]]
                if p[1] in src:
                    ents.append(e)
        good.append({
            "id": f"{d['id']}-a{i}",
            "text": cl.get("text", "")[:500],
            "confidence": cl.get("confidence", "medium") if cl.get("confidence") in ("high", "medium", "low") else "medium",
            "quote": quote[:300],
            "entities": ents,
            "geo": cl.get("geo", "unknown") if cl.get("geo") in ("ru", "foreign", "both", "unknown") else "unknown",
        })
    if not good:
        return None
    return {"doc_id": d["id"], "summary": "", "geo": d.get("geo_hint", "unknown"),
            "claims": good, "relations": [], "experts": [], "auto": True}


def main():
    docs = [json.loads(l) for l in open(os.path.join(CACHE, "docs.jsonl"), encoding="utf-8")]
    have = {fn[:-5] for fn in os.listdir(EXTRACTED) if fn.endswith(".json")}
    # приоритет: обзоры/статьи среднего размера (не ценовые таблицы, не гигантские сборники)
    def prio(d):
        fn = d["filename"].lower()
        score = 0
        if d["ext"] in ("docx", "pdf"):
            score += 2
        if any(k in fn for k in ("обзор", "ои", "статья", "методы", "технолог", "производств")):
            score += 3
        if 20000 < d["n_chars"] < 400000:
            score += 2
        if any(k in fn for k in ("prices", "quarterly", "flysheet")):
            score -= 5
        return -score
    todo = [d for d in sorted(docs, key=prio) if d["id"] not in have][:MAX_DOCS]
    print(f"LLM-extraction queue: {len(todo)} docs (provider order: {llm._PROVIDER_ORDER})", flush=True)

    ok = fail = 0
    t0 = time.time()
    for i, d in enumerate(todo, 1):
        try:
            res = extract_doc(d)
        except Exception as e:
            res = None
            print(f"  [{i}] EXC {repr(e)[:80]}", flush=True)
        if res:
            with open(os.path.join(EXTRACTED, d["id"] + ".json"), "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, indent=1)
            ok += 1
            print(f"  [{i}/{len(todo)}] +{len(res['claims'])} claims ({llm.active_provider()}) "
                  f"{d['title'][:50]}", flush=True)
        else:
            fail += 1
            print(f"  [{i}/{len(todo)}] skip {d['title'][:50]}", flush=True)
    print(f"\nDONE ok={ok} fail={fail} in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()

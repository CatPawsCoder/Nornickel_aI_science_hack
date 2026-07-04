# -*- coding: utf-8 -*-
"""Лёгкий поисковый индекс: SQLite FTS5 (для VPS с малой RAM).

Вместо 877МБ pickle в памяти — дисковая база с встроенным BM25-ранжированием.
Чанкование и стемминг — те же, что в search.py (единая логика релевантности).
Выход: data/cache/fts.db (~0.5ГБ на диске, <50МБ RAM при поиске).
"""
import json
import os
import re
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from search import tokenize  # тот же стеммер

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "cache")
FTS_DB = os.path.join(CACHE, "fts.db")


def chunks_of(text: str):
    paras = re.split(r"\n\s*\n", text)
    buf = ""
    for p in paras:
        if len(buf) + len(p) > 1400 and buf:
            yield buf
            buf = p
        else:
            buf = (buf + "\n\n" + p) if buf else p
    if buf.strip():
        yield buf


def main():
    t0 = time.time()
    if os.path.exists(FTS_DB):
        os.remove(FTS_DB)
    db = sqlite3.connect(FTS_DB)
    db.executescript("""
        PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
        CREATE TABLE chunk(id INTEGER PRIMARY KEY, doc_id TEXT, text TEXT);
        CREATE VIRTUAL TABLE chunk_fts USING fts5(stemmed, content='');
    """)
    docs = [json.loads(l) for l in open(os.path.join(CACHE, "docs.jsonl"), encoding="utf-8")]
    # дедуп-список из build_graph_mp: индексируем те же документы, что и граф
    keep_p = os.path.join(CACHE, "keep_docs.json")
    if os.path.exists(keep_p):
        keep = set(json.load(open(keep_p, encoding="utf-8")))
        docs = [d for d in docs if d["id"] in keep]
        print(f"docs after dedup filter: {len(docs)}")
    n = 0
    for di, d in enumerate(docs):
        try:
            text = open(os.path.join(ROOT, d["text_path"]), encoding="utf-8").read()
        except Exception:
            continue
        rows, fts_rows = [], []
        for ch in chunks_of(text):
            n += 1
            rows.append((n, d["id"], ch[:4000]))
            fts_rows.append((n, " ".join(tokenize(ch))))
        db.executemany("INSERT INTO chunk VALUES (?,?,?)", rows)
        db.executemany("INSERT INTO chunk_fts(rowid, stemmed) VALUES (?,?)", fts_rows)
        if (di + 1) % 300 == 0:
            db.commit()
            print(f"  {di+1}/{len(docs)} chunks={n} {time.time()-t0:.0f}s", flush=True)
    db.commit()
    db.execute("INSERT INTO chunk_fts(chunk_fts) VALUES('optimize')")
    db.commit()
    db.close()
    print(f"DONE: {n} chunks, {os.path.getsize(FTS_DB)/1e6:.0f} MB, {time.time()-t0:.0f}s")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()

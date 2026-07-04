# -*- coding: utf-8 -*-
"""OCR сканированных PDF (без текстового слоя) через easyocr на GPU (RTX 5090).

Читает data/cache/needs_ocr.json, рендерит страницы в изображения (PyMuPDF),
распознаёт rus+eng, дописывает в docs.jsonl / txt/ с пометкой source=ocr.

Капы: не более MAX_PAGES страниц на документ (большие сканы-журналы —
только начало, чтобы уложиться в дедлайн). Настраивается.
"""
import json
import os
import sys
import re

import fitz
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "cache")
TXT = os.path.join(CACHE, "txt")
FULL = os.path.join(ROOT, "data", "raw", "full")

MAX_PAGES = int(os.environ.get("OCR_MAX_PAGES", "40"))
DPI = 200

YEAR_RE = re.compile(r"(19[89]\d|20[0-2]\d)")


def main():
    import easyocr
    reader = easyocr.Reader(["ru", "en"], gpu=True)

    scans = json.load(open(os.path.join(CACHE, "needs_ocr.json"), encoding="utf-8"))
    print(f"OCR queue: {len(scans)} files", flush=True)

    done = set()
    out_path = os.path.join(CACHE, "docs.jsonl")
    for line in open(out_path, encoding="utf-8"):
        try:
            done.add(json.loads(line)["id"])
        except Exception:
            pass

    ok = 0
    with open(out_path, "a", encoding="utf-8") as out:
        for si, sc in enumerate(scans):
            doc_id, fn, npages = sc["id"], sc["filename"], sc.get("npages") or 0
            if doc_id in done:
                continue
            path = os.path.join(FULL, fn)
            if not os.path.exists(path):
                continue
            try:
                doc = fitz.open(path)
                pages_to_do = min(len(doc), MAX_PAGES)
                chunks = []
                for pi in range(pages_to_do):
                    pix = doc[pi].get_pixmap(dpi=DPI)
                    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                        pix.height, pix.width, pix.n)
                    if pix.n == 4:
                        img = img[:, :, :3]
                    lines = reader.readtext(img, detail=0, paragraph=True)
                    chunks.append("\n".join(lines))
                doc.close()
                text = re.sub(r"[ \t]+", " ", "\n".join(chunks)).strip()
                if len(text) < 100:
                    print(f"  [{si+1}] {fn[:50]} -> too little OCR text ({len(text)})", flush=True)
                    continue
                txt_path = os.path.join(TXT, doc_id + ".txt")
                open(txt_path, "w", encoding="utf-8").write(text)
                yr = YEAR_RE.findall(fn) or YEAR_RE.findall(text[:2000])
                rec = {
                    "id": doc_id, "filename": fn, "ext": "pdf",
                    "title": re.sub(r"^\d{4}_", "", os.path.splitext(fn)[0])[:120],
                    "year": int(yr[-1]) if yr else None,
                    "lang": "ru", "geo_hint": "unknown",
                    "n_chars": len(text),
                    "text_path": os.path.relpath(txt_path, ROOT),
                    "source": "ocr",
                }
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out.flush()
                ok += 1
                print(f"  [{si+1}/{len(scans)}] OCR ok: {fn[:50]} "
                      f"({pages_to_do}p, {len(text)} chars)", flush=True)
            except Exception as e:
                print(f"  [{si+1}] FAIL {fn[:50]}: {repr(e)[:120]}", flush=True)
    print(f"\nOCR DONE: {ok} files added", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()

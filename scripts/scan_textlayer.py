# -*- coding: utf-8 -*-
"""Быстрый скан PDF: у каких есть текстовый слой, а какие — сканы (нужен OCR)."""
import os, sys, json
import fitz
sys.stdout.reconfigure(encoding="utf-8")

FULL = r"C:\Users\Asus ROG\nauchny-klubok\data\raw\full"
files = [f for f in os.listdir(FULL) if f.lower().endswith(".pdf")]
print("total PDF:", len(files))

has_text, scan, err = [], [], []
for i, fn in enumerate(files):
    path = os.path.join(FULL, fn)
    try:
        doc = fitz.open(path)
        npages = len(doc)
        # берём выборку страниц: первые 3 + середина
        sample_pages = list(range(min(3, npages)))
        if npages > 4:
            sample_pages.append(npages // 2)
        chars = 0
        for pg in sample_pages:
            chars += len(doc[pg].get_text("text").strip())
        doc.close()
        chars_per_page = chars / max(1, len(sample_pages))
        if chars_per_page < 80:   # почти нет текста -> скан
            scan.append((fn, npages, round(chars_per_page)))
        else:
            has_text.append((fn, npages, round(chars_per_page)))
    except Exception as e:
        err.append((fn, repr(e)[:80]))
    if (i + 1) % 200 == 0:
        print(f"  scanned {i+1}/{len(files)}", flush=True)

print(f"\nHAS TEXT LAYER: {len(has_text)}")
print(f"SCAN (need OCR): {len(scan)}")
print(f"ERRORS: {len(err)}")
total_scan_pages = sum(p for _, p, _ in scan)
print(f"total pages to OCR: {total_scan_pages}")
with open(r"C:\Users\Asus ROG\nauchny-klubok\data\cache\scan_pdfs.json", "w", encoding="utf-8") as f:
    json.dump({"scan": scan, "has_text_count": len(has_text), "errors": err}, f, ensure_ascii=False)
print("\nПримеры сканов:")
for fn, np_, cpp in scan[:15]:
    print(f"  {np_:4d}p  {cpp:4d}ch/p  {fn[:70]}")

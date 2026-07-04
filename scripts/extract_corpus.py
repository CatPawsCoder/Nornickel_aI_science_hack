# -*- coding: utf-8 -*-
"""Распаковка полного корпуса из 4.7GB zip, включая вложенные архивы.

Имена в архиве в кодировке cp866/cp437 (mojibake) — восстанавливаем.
Вложенные .zip/.rar/.001 распаковываются рекурсивно.
Результат: data/raw/full/<плоские файлы с безопасными именами> + manifest.jsonl
"""
import hashlib
import json
import os
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8")

SRC = r"C:\Users\Asus ROG\OneDrive\Desktop\Задача 2. Научный клубок.zip"
ROOT = r"C:\Users\Asus ROG\nauchny-klubok"
OUT = os.path.join(ROOT, "data", "raw", "full")
os.makedirs(OUT, exist_ok=True)

DOC_EXT = {"pdf", "docx", "doc", "docm", "pptx", "xls", "xlsx", "txt", "rtf"}
ARCHIVE_EXT = {"zip", "rar", "001"}

manifest = []


def fix_name(name: str) -> str:
    """Восстановить mojibake-имя из zip (cp437->cp866)."""
    try:
        return name.encode("cp437").decode("cp866")
    except Exception:
        return name


def safe_filename(orig_path: str, idx: int) -> str:
    base = os.path.basename(orig_path.replace("\\", "/"))
    stem, ext = os.path.splitext(base)
    ext = ext.lower().lstrip(".")
    h = hashlib.md5(orig_path.encode("utf-8", "ignore")).hexdigest()[:8]
    # оставляем читаемый префикс имени (первые 60 симв.), плюс хэш от полного пути
    safe_stem = "".join(c for c in stem if c.isalnum() or c in " -_,.()").strip()[:60]
    return f"{idx:04d}_{safe_stem}_{h}.{ext}" if safe_stem else f"{idx:04d}_{h}.{ext}"


def extract_zip(zf: zipfile.ZipFile, source_label: str, counter: list):
    for info in zf.infolist():
        if info.is_dir():
            continue
        raw_name = info.filename
        disp = fix_name(raw_name)
        ext = disp.rsplit(".", 1)[-1].lower() if "." in disp else ""
        if ext in DOC_EXT:
            counter[0] += 1
            idx = counter[0]
            out_name = safe_filename(disp, idx)
            out_path = os.path.join(OUT, out_name)
            try:
                with zf.open(info) as f:
                    data = f.read()
                with open(out_path, "wb") as g:
                    g.write(data)
                manifest.append({
                    "idx": idx, "out": out_name, "orig": disp,
                    "ext": ext, "source": source_label, "size": len(data)})
            except Exception as e:
                manifest.append({"idx": idx, "orig": disp, "ext": ext,
                                 "source": source_label, "error": repr(e)[:150]})
        elif ext == "zip":
            # вложенный zip — распаковать рекурсивно из памяти
            import io
            try:
                with zf.open(info) as f:
                    nested = io.BytesIO(f.read())
                with zipfile.ZipFile(nested) as nzf:
                    extract_zip(nzf, source_label + " > " + disp, counter)
            except Exception as e:
                print("nested zip fail:", disp, repr(e)[:100])
        # rar/.001 — пометим в manifest как требующие внешнего распаковщика
        elif ext in ("rar", "001", "002"):
            manifest.append({"orig": disp, "ext": ext, "source": source_label,
                             "note": "archive_needs_external_unpack"})


def main():
    counter = [0]
    with zipfile.ZipFile(SRC) as zf:
        extract_zip(zf, "root", counter)
    with open(os.path.join(ROOT, "data", "cache", "corpus_manifest.jsonl"), "w", encoding="utf-8") as f:
        for m in manifest:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    ok = [m for m in manifest if "out" in m]
    from collections import Counter
    exts = Counter(m["ext"] for m in ok)
    print(f"extracted files: {len(ok)}")
    print("by ext:", dict(exts))
    rar = [m for m in manifest if m.get("note") == "archive_needs_external_unpack"]
    print(f"rar/split archives (need external unpack): {len(rar)}")
    for m in rar[:20]:
        print("  ", m["orig"])


if __name__ == "__main__":
    main()

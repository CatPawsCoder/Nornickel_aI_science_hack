# -*- coding: utf-8 -*-
import zipfile, sys
from collections import Counter
sys.stdout.reconfigure(encoding="utf-8")
z = zipfile.ZipFile(r"C:\Users\Asus ROG\OneDrive\Desktop\Задача 2. Научный клубок.zip")
names = z.namelist()
tops = Counter(); exts = Counter(); files = 0
sep = chr(92)  # backslash
for n in names:
    parts = n.replace(sep, "/").split("/")
    if n.endswith("/"):
        continue
    files += 1
    if len(parts) > 1:
        tops[parts[0]] += 1
    last = parts[-1]
    if "." in last:
        exts[last.split(".")[-1].lower()] += 1
print("total entries:", len(names))
print("files (non-dir):", files)
print("--- top-level folders ---")
for k, v in tops.most_common():
    print(f"  {v:6d}  {k}")
print("--- extensions ---")
for k, v in exts.most_common(30):
    print(f"  {v:6d}  .{k}")

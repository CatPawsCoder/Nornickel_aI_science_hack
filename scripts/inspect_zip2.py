# -*- coding: utf-8 -*-
import zipfile, sys
from collections import Counter
sys.stdout.reconfigure(encoding="utf-8")
z = zipfile.ZipFile(r"C:\Users\Asus ROG\OneDrive\Desktop\Задача 2. Научный клубок.zip")
sep = chr(92)
# second-level folders (subdirectories under the single top folder)
subs = Counter()
sub_ext = {}
for info in z.infolist():
    n = info.filename.replace(sep, "/")
    if n.endswith("/"):
        continue
    parts = n.split("/")
    if len(parts) >= 3:
        key = parts[1]
    elif len(parts) == 2:
        key = "(корень)"
    else:
        key = "(top)"
    subs[key] += 1
    ext = parts[-1].split(".")[-1].lower() if "." in parts[-1] else "?"
    sub_ext.setdefault(key, Counter())[ext] += 1
print("--- второй уровень (тематические папки) ---")
for k, v in subs.most_common():
    top_exts = ", ".join(f"{e}:{c}" for e, c in sub_ext[k].most_common(5))
    # re-encode key from cp437 mojibake to cp866 if possible
    try:
        fixed = k.encode("cp437").decode("cp866")
    except Exception:
        fixed = k
    print(f"  {v:5d}  {fixed}   [{top_exts}]")

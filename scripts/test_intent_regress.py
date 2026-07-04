# -*- coding: utf-8 -*-
"""Регрессионные тесты intent-детектора (обязательный набор из ревью).

missing_intent должен быть пуст для тем, представленных в базе,
и содержать якорь только для реально отсутствующих операций.
"""
import sys
import time

sys.path.insert(0, "backend")
sys.stdout.reconfigure(encoding="utf-8")
from search import load_index, search
from graph import open_db

idx = load_index()
conn = open_db(read_only=True)

CASES = [
    ("SO2", "Обзор способов удаления SO2 из отходящих газов металлургических предприятий мира.", []),
    ("католит", "Литературный обзор технических решений циркуляции католита при электроэкстракции никеля и её оптимальной скорости", []),
    ("гипс", "Провести литературный обзор источников техногенного гипса и способов его переработки", []),
    ("Pb-Zn", "Обзор современных способов переработки свинцово-цинкового сырья. Мировая практика.", []),
    ("закачка", "Анализ технологий и примеров закачки шахтных вод в глубокие горизонты", ["закачка в глубокие горизонты"]),
    ("закладка", "Обзор практик использования угля и отходов угольной промышленности для закладки выработанного пространства", None),  # якорь допустим, если данных нет
]

fails = 0
for tag, q, expected in CASES:
    t0 = time.time()
    r = search(q, idx, conn)
    mi = r["missing_intent"]
    dt = time.time() - t0
    if expected is None:
        ok = all("закладка" in m for m in mi)  # только правильный якорь, без мусора
    else:
        ok = mi == expected
    fails += 0 if ok else 1
    print(f"{'✅' if ok else '❌'} {tag:10s} search={dt:4.2f}s missing_intent={mi}")

print(f"\n{'ВСЕ ТЕСТЫ ПРОЙДЕНЫ' if fails == 0 else f'ПРОВАЛОВ: {fails}'}")
sys.exit(1 if fails else 0)

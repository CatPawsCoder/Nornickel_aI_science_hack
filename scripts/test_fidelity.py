# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, "backend")
sys.stdout.reconfigure(encoding="utf-8")
from search import load_index, search, parse_query
from graph import open_db
from answer import synthesize, _fmt_constraint

idx = load_index()
conn = open_db(read_only=True)
fails = 0

def check(name, cond):
    global fails
    print(("✅" if cond else "❌"), name)
    fails += 0 if cond else 1

# 1. AND-разворот: сульфаты и хлориды -> ДВА условия + сухой остаток = 3
q1 = "Какие методы обессоливания воды подходят, если вода содержит сульфаты и хлориды 200-300 мг/л, а требуемый сухой остаток не более 1000 мг/дм3?"
r1 = search(q1, idx, conn)
params = [w["param"] for w in r1["parsed"]["numeric"]]
check(f"3 отдельных условия {params}", sorted(params) == ["сульфаты", "сухой остаток", "хлориды"])
check(f"n_constraints=3 (было 2)", r1["n_constraints"] == 3)

# 2. отображение ≤
f = [w for w in r1["parsed"]["numeric"] if w["param"] == "сухой остаток"][0]
s = _fmt_constraint(f)
check(f"формат «{s}» содержит ≤", "≤1000" in s)

# 3. прямой ответ обессоливания: без подмены веществ в отрицании
a1 = synthesize(r1, idx["docs"])
d1 = " ".join(a1["markdown"].split("##")[1].split())
bad_negation = ("не подходят для удаления хлоридов и сульфатов" in d1 or
                "не подходят для удаления сульфатов и хлоридов" in d1)
check("нет искажённого отрицания про сульфаты", not bad_negation)
print("    direct:", d1[:260])

# 4. intent-регресс (сокращённый)
for tag, q, expect_empty in [("SO2", "Обзор способов удаления SO2 из отходящих газов металлургических предприятий мира.", True),
                             ("закачка", "Анализ технологий закачки шахтных вод в глубокие горизонты", False)]:
    mi = search(q, idx, conn)["missing_intent"]
    check(f"intent {tag}: {mi}", (len(mi) == 0) == expect_empty)

# 5. ключевые регрессы ответов
for tag, q, needle in [("Waterval", "Сколько процентов извлечение МПГ из гранулированного шлака Waterval?", "60"),
                       ("HiPRO", "Что такое трехстадийный процесс HiPRO?", "98"),
                       ("католит", "технические решения циркуляции католита при электроэкстракции никеля и оптимальная скорость", "л/ч")]:
    a = synthesize(search(q, idx, conn), idx["docs"])
    d = a["markdown"].split("##")[1]
    check(f"{tag}: «{needle}» в ответе", needle in d)

print(("\nВСЕ ПРОЙДЕНЫ" if fails == 0 else f"\nПРОВАЛОВ: {fails}"))
sys.exit(1 if fails else 0)

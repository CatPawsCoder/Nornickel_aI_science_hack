# -*- coding: utf-8 -*-
"""Детерминированное извлечение числовых ограничений из технического текста.

Грамматика: [параметр-контекст] [оператор] значение [- значение] единица
Примеры: «сульфаты ≤300 мг/л», «температура 60–80 °C», «скорость потока 5 м3/ч»,
         «сухой остаток не более 1000 мг/дм3», «извлечение 95,5 %».

Каждый факт хранит span (start, end) и точную исходную подстроку => валидация
string-match: число в графе обязано дословно присутствовать в источнике.
LLM эти значения НЕ генерирует и НЕ изменяет.
"""
import re
from dataclasses import dataclass, asdict

# --- единицы измерения (RU + EN варианты) --------------------------------
UNITS = [
    # концентрации
    r"мг/дм3|мг/дм³|мг/дмЗ|мг/л|г/дм3|г/дм³|г/л|мкг/л|г/т|мг/м3|мг/м³|kg/t|кг/т|kg/m3|g/l|g/L|mg/l|mg/L|ppm|ppb",
    # проценты и доли
    r"%|проц\.|масс\.\s?%|об\.\s?%|ат\.\s?%|wt\.?\s?%",
    # температура
    r"°С|°C|оС|гр\.\s?С|К\b|K\b",
    # давление
    r"МПа|кПа|ГПа|атм|бар|bar|мм\s?рт\.\s?ст\.|psi|Па",
    # скорость / расход
    r"м3/ч|м³/ч|м3/сут|м³/сут|м/с|м/ч|м/мин|см/с|л/мин|л/ч|л/с|м3/мин|dm3/min|m3/h|t/h",
    # производительность / масса
    r"т/сут|т/ч|т/год|тыс\.\s?т|млн\s?т|kt|Mt|т\b|кг\b|кг/ч",
    # электрохимия
    r"А/м2|А/м²|A/m2|мА/см2|мА/см²|В\b|мВ|kA|кА|А\b|Вт|кВт|МВт|кВт·ч|кВтч/т|kWh/t",
    # геометрия
    r"мкм|мм\b|см\b|м\b|км\b|нм\b",
    # время
    r"час(?:ов|а)?\b|ч\b|мин\b|сут(?:ок)?\b|с\b|лет\b|года?\b",
    # экономика
    r"руб\.|руб/т|долл\.|USD|\$/т|USD/t|€|млн\s?долл\.|млрд\s?руб\.",
    # прочее техническое
    r"г/см3|г/см³|кг/м3|кг/м³|Гц|об/мин|rpm|мВт|pH|ед\.\s?pH",
]
UNIT_RE = "|".join(f"(?:{u})" for u in UNITS)

# --- операторы -----------------------------------------------------------
OPS = [
    (r"≤|<=|не\s+более|не\s+выше|до\s(?=\d)|менее|ниже|max\.?|макс\.?", "<="),
    (r"≥|>=|не\s+менее|не\s+ниже|свыше|более|выше|от\s(?=\d)|min\.?|мин\.?", ">="),
    (r"<", "<"),
    (r">", ">"),
    (r"около|порядка|примерно|~|≈|circa", "~"),
]
OP_RE = "|".join(f"(?:{p})" for p, _ in OPS)

SP = r"[ \xa0  ]"  # пробелы без переноса строки
NUM = rf"\d{{1,3}}(?:{SP}\d{{3}})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
RANGE_SEP = rf"{SP}*(?:[-–—÷]|\.\.\.|до){SP}*"

# полный паттерн: (оператор)? число (диапазон)? единица
FACT_RE = re.compile(
    rf"(?P<op>(?:{OP_RE})\s*)?"
    rf"(?P<v1>{NUM})"
    rf"(?:(?P<sep>{RANGE_SEP})(?P<v2>{NUM}))?"
    rf"\s*(?P<unit>{UNIT_RE})",
    re.IGNORECASE,
)

# параметры-контексты: что измеряется (ищем слева от числа в окне)
PARAM_HINTS = [
    ("концентрация", r"концентрац|содержан|содержит"),
    ("сульфаты", r"сульфат|SO4|SO₄"),
    ("хлориды", r"хлорид|Cl-|Cl⁻"),
    ("сухой остаток", r"сухой\s+остаток|минерализац|солесодержан"),
    ("температура", r"температур|нагрев|охлажден|t\s*="),
    ("давление", r"давлен"),
    ("скорость потока", r"скорост[ьи]\s+(?:потока|циркуляц|подач|движения)|расход"),
    ("скорость", r"скорост"),
    ("плотность тока", r"плотност[ьи]\s+тока|катодн\w+\s+плотност"),
    ("извлечение", r"извлечен|выход|recovery"),
    ("производительность", r"производительност|мощност"),
    ("pH", r"\bpH\b|кислотност"),
    ("крупность", r"крупност|измельчен|помол|класс\s*-"),
    ("напряжение", r"напряжен"),
    ("выход по току", r"выход\w*\s+по\s+току"),
    ("затраты", r"затрат|стоимост|капзатрат|CAPEX|OPEX|себестоимост"),
    ("глубина", r"глубин"),
]
PARAM_RES = [(name, re.compile(p, re.I)) for name, p in PARAM_HINTS]

# материалы/вещества рядом с числом уточняют параметр
SUBSTANCE_HINTS = re.compile(
    r"никел|медь|меди|кобальт|железо|Ni|Cu|Co|Fe|Zn|Pb|As|Au|Ag|Pt|Pd|Rh|МПГ|"
    r"кальци|магни|натри|Ca|Mg|Na|H2SO4|серн\w+\s+кислот|аммиак|NH3|гипс|CaSO4|"
    r"SO2|SO₂|диоксид\w*\s+серы", re.I)


def normalize_num(s: str) -> float:
    for sp in (" ", "\xa0", " ", " "):
        s = s.replace(sp, "")
    return float(s.replace(",", "."))


def normalize_op(op_raw: str | None) -> str:
    if not op_raw:
        return "="
    t = op_raw.strip().lower()
    for pat, canon in OPS:
        if re.fullmatch(pat, t, re.I):
            return canon
    for pat, canon in OPS:
        if re.match(pat, t, re.I):
            return canon
    return "="


@dataclass
class NumericFact:
    param: str          # что измеряется (эвристика по контексту)
    substance: str      # вещество/материал рядом (если найден)
    op: str             # =, <=, >=, <, >, ~, range
    value: float        # нижнее значение
    value2: float | None  # верхнее значение диапазона
    unit: str           # единица как в тексте
    quote: str          # ДОСЛОВНАЯ подстрока из источника (для верификации)
    context: str        # окно ±120 символов
    start: int
    end: int
    all_params: list = None  # все параметры-хинты в левом окне (для запросов вида
                              # «сульфаты, хлориды, Ca, Mg, Na по 200-300 мг/л»)

    def to_dict(self):
        return asdict(self)


def extract_numeric_facts(text: str, window: int = 120) -> list[NumericFact]:
    facts = []
    prev_fact_end = 0  # конец предыдущего числового факта
    for m in FACT_RE.finditer(text):
        start, end = m.start(), m.end()
        left = text[max(0, start - window):start]
        # сегмент строго МЕЖДУ предыдущим фактом и текущим числом:
        # перечисление «сульфаты, хлориды, Na по 200-300 мг/л» живёт только здесь.
        # Без этой отсечки параметры предыдущего ограничения («сульфаты 200-300,
        # а сухой остаток ≤1000») ложно приписывались следующему числу.
        seg_left = text[max(0, start - window, prev_fact_end):start]
        right = text[end:end + 40]
        ctx = (left + text[start:end] + right).replace("\n", " ")

        # отсечь мусор: номера страниц, годы, ссылки на литературу
        v1 = normalize_num(m.group("v1"))
        unit = m.group("unit").strip()
        if unit in ("г", "м", "с", "К", "В", "А", "т", "ч") and not m.group("op"):
            # односимвольные единицы без оператора часто ложные — требуем параметр рядом
            if not any(p.search(left[-60:]) for _, p in PARAM_RES):
                continue
        if unit.lower() in ("года", "год", "лет") :
            continue  # даты не являются техническими ограничениями

        # параметр = ближайшее к числу упоминание (максимальная позиция слева
        # в широком окне — для полноты атрибуции по корпусу);
        # all_params — ТОЛЬКО из сегмента после предыдущего факта: это перечисление
        # веществ, относящееся именно к текущему числу
        param, best_pos = "параметр", -1
        for name, p in PARAM_RES:
            last = None
            for pm in p.finditer(left):
                last = pm
            if last and last.end() > best_pos:
                param, best_pos = name, last.end()
        seg_found = []
        for name, p in PARAM_RES:
            last = None
            for pm in p.finditer(seg_left):
                last = pm
            if last:
                seg_found.append((last.end(), name))
        seg_found.sort(key=lambda t: -t[0])
        seen_names = []
        for _, name in seg_found:
            if name not in seen_names:
                seen_names.append(name)
        # главный параметр обязан быть в списке (если он из сегмента);
        # если сегмент пуст — остаётся только ближайший параметр
        if param != "параметр" and param not in seen_names:
            seen_names = [param]
        prev_fact_end = end

        # вещество: ближайшее слева в сегменте текущего факта (или сразу справа)
        subst = ""
        last_s = None
        for sm in SUBSTANCE_HINTS.finditer(seg_left[-80:]):
            last_s = sm
        if last_s:
            subst = last_s.group(0)
        else:
            sm = SUBSTANCE_HINTS.search(right)
            if sm:
                subst = sm.group(0)

        v2 = normalize_num(m.group("v2")) if m.group("v2") else None
        op = "range" if v2 is not None else normalize_op(m.group("op"))

        facts.append(NumericFact(
            param=param, substance=subst, op=op,
            value=v1, value2=v2, unit=unit,
            all_params=seen_names or [param],
            quote=text[start:end],
            context=ctx.strip(), start=start, end=end,
        ))
    return facts


def validate_fact(fact: dict, source_text: str) -> bool:
    """Верификация: цитата обязана дословно присутствовать в источнике."""
    return fact["quote"] in source_text


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    demo = ("Исходная вода содержит сульфаты ≤300 мг/л, хлориды 200–300 мг/л, "
            "требуемый сухой остаток — не более 1000 мг/дм3. Температура электролита "
            "поддерживалась 60–65 °С при катодной плотности тока 250 А/м2. "
            "Скорость циркуляции католита составляла около 20 л/мин, "
            "извлечение никеля достигало 98,5 %.")
    for f in extract_numeric_facts(demo):
        print(f"{f.param:22s} {f.substance:10s} {f.op:6s} {f.value}"
              f"{('-' + str(f.value2)) if f.value2 else '':10s} {f.unit:8s} | «{f.quote}»")

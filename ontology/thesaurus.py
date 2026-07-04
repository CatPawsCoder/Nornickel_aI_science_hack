# -*- coding: utf-8 -*-
"""Тезаурус предметной области: канонические сущности + синонимы RU/EN.

Роль в гибридной архитектуре: детерминированный канонизатор.
LLM-слой предлагает сущности, тезаурус нормализует к каноническому ID;
слой словарного споттинга размечает MENTIONS по всему корпусу без LLM.
"""

# canon_id -> {name, name_en, type, synonyms: [...]}
MATERIALS = {
    "nickel":        {"name": "никель", "en": "nickel", "kind": "metal",
                      "syn": ["Ni", "никеля", "никелевый", "никелевая", "никелевых", "nickel"]},
    "copper":        {"name": "медь", "en": "copper", "kind": "metal",
                      "syn": ["Cu", "меди", "медный", "медная", "медных", "copper"]},
    "cobalt":        {"name": "кобальт", "en": "cobalt", "kind": "metal",
                      "syn": ["Co", "кобальта", "кобальтовый", "cobalt"]},
    "pgm":           {"name": "МПГ", "en": "PGM", "kind": "metal",
                      "syn": ["металлы платиновой группы", "платиноиды", "платиновые металлы",
                              "platinum group metals", "PGMs", "ЭПГ"]},
    "gold":          {"name": "золото", "en": "gold", "kind": "metal",
                      "syn": ["Au", "золота", "gold"]},
    "silver":        {"name": "серебро", "en": "silver", "kind": "metal",
                      "syn": ["Ag", "серебра", "silver"]},
    "platinum":      {"name": "платина", "en": "platinum", "kind": "metal",
                      "syn": ["Pt", "платины", "platinum"]},
    "palladium":     {"name": "палладий", "en": "palladium", "kind": "metal",
                      "syn": ["Pd", "палладия", "palladium"]},
    "matte":         {"name": "штейн", "en": "matte", "kind": "intermediate",
                      "syn": ["штейна", "штейне", "штейном", "файнштейн", "файнштейна", "matte"]},
    "slag":          {"name": "шлак", "en": "slag", "kind": "waste",
                      "syn": ["шлака", "шлаки", "шлаков", "шлаковый", "slag"]},
    "sulfates":      {"name": "сульфаты", "en": "sulfates", "kind": "ion",
                      "syn": ["сульфат", "сульфатов", "SO4", "SO₄", "sulfate", "sulphate"]},
    "chlorides":     {"name": "хлориды", "en": "chlorides", "kind": "ion",
                      "syn": ["хлорид", "хлоридов", "chloride"]},
    "calcium":       {"name": "кальций", "en": "calcium", "kind": "element",
                      "syn": ["Ca", "кальция", "calcium"]},
    "magnesium":     {"name": "магний", "en": "magnesium", "kind": "element",
                      "syn": ["Mg", "магния", "magnesium"]},
    "sodium":        {"name": "натрий", "en": "sodium", "kind": "element",
                      "syn": ["Na", "натрия", "sodium"]},
    "iron":          {"name": "железо", "en": "iron", "kind": "metal",
                      "syn": ["Fe", "железа", "железистый", "iron"]},
    "sulfuric_acid": {"name": "серная кислота", "en": "sulfuric acid", "kind": "reagent",
                      "syn": ["H2SO4", "H₂SO₄", "серной кислоты", "sulfuric acid", "sulphuric acid"]},
    "so2":           {"name": "диоксид серы", "en": "SO2", "kind": "gas",
                      "syn": ["SO2", "SO₂", "сернистый газ", "сернистый ангидрид", "диоксида серы"]},
    "gypsum":        {"name": "гипс", "en": "gypsum", "kind": "byproduct",
                      "syn": ["гипса", "CaSO4", "техногенный гипс", "ангидрит", "ангидрита", "gypsum", "anhydrite"]},
    "catholyte":     {"name": "католит", "en": "catholyte", "kind": "solution",
                      "syn": ["католита", "католите", "catholyte"]},
    "anolyte":       {"name": "анолит", "en": "anolyte", "kind": "solution",
                      "syn": ["анолита", "anolyte"]},
    "electrolyte":   {"name": "электролит", "en": "electrolyte", "kind": "solution",
                      "syn": ["электролита", "электролите", "electrolyte"]},
    "mine_water":    {"name": "шахтная вода", "en": "mine water", "kind": "effluent",
                      "syn": ["шахтные воды", "шахтных вод", "рудничные воды", "рудничных вод", "mine water"]},
    "sulfide_ore":   {"name": "сульфидная руда", "en": "sulfide ore", "kind": "ore",
                      "syn": ["сульфидные руды", "сульфидных руд", "сульфидной руды", "sulfide ore", "sulphide ore"]},
    "laterite_ore":  {"name": "латеритная руда", "en": "laterite ore", "kind": "ore",
                      "syn": ["латеритные руды", "латеритных руд", "латериты", "латеритов", "laterite"]},
    "concentrate":   {"name": "концентрат", "en": "concentrate", "kind": "intermediate",
                      "syn": ["концентрата", "концентраты", "концентратов", "concentrate"]},
    "tailings":      {"name": "хвосты обогащения", "en": "tailings", "kind": "waste",
                      "syn": ["хвосты", "хвостов", "хвостохранилище", "tailings"]},
    "nickel_cathode": {"name": "никелевый катод", "en": "nickel cathode", "kind": "product",
                      "syn": ["катодный никель", "катодного никеля", "никелевые катоды", "nickel cathode"]},
    "nickel_sulfate": {"name": "сульфат никеля", "en": "nickel sulfate", "kind": "product",
                      "syn": ["сульфата никеля", "NiSO4", "nickel sulfate", "nickel sulphate"]},
    "lithium":       {"name": "литий", "en": "lithium", "kind": "metal",
                      "syn": ["Li", "лития", "lithium"]},
    "arsenic":       {"name": "мышьяк", "en": "arsenic", "kind": "impurity",
                      "syn": ["As", "мышьяка", "arsenic"]},
    "lead":          {"name": "свинец", "en": "lead", "kind": "impurity",
                      "syn": ["Pb", "свинца", "lead"]},
    "coal_waste":    {"name": "угольные отходы", "en": "coal waste", "kind": "waste",
                      "syn": ["угольных отходов", "угольные шламы", "coal waste"]},
}

PROCESSES = {
    "heap_leaching":     {"name": "кучное выщелачивание", "en": "heap leaching", "domain": "гидрометаллургия",
                          "syn": ["кучного выщелачивания", "КВ", "heap leaching", "heap leach"]},
    "autoclave_leaching": {"name": "автоклавное выщелачивание", "en": "pressure leaching", "domain": "гидрометаллургия",
                          "syn": ["автоклавного выщелачивания", "автоклавное вскрытие", "HPAL",
                                  "pressure leaching", "POX", "pressure oxidation"]},
    "leaching":          {"name": "выщелачивание", "en": "leaching", "domain": "гидрометаллургия",
                          "syn": ["выщелачивания", "выщелачиванием", "leaching"]},
    "electrowinning":    {"name": "электроэкстракция", "en": "electrowinning", "domain": "гидрометаллургия",
                          "syn": ["электроэкстракции", "электроэкстракцией", "ЭЭ", "electrowinning", "EW",
                                  "электроосаждение", "электроосаждения"]},
    "electrorefining":   {"name": "электрорафинирование", "en": "electrorefining", "domain": "гидрометаллургия",
                          "syn": ["электрорафинирования", "ЭР", "electrorefining", "ER"]},
    "solvent_extraction": {"name": "жидкостная экстракция", "en": "solvent extraction", "domain": "гидрометаллургия",
                          "syn": ["экстракция органическими растворителями", "SX", "solvent extraction",
                                  "экстракционная очистка"]},
    "flotation":         {"name": "флотация", "en": "flotation", "domain": "обогащение",
                          "syn": ["флотации", "флотацией", "флотационное обогащение", "flotation"]},
    "flash_smelting":    {"name": "взвешенная плавка", "en": "flash smelting", "domain": "пирометаллургия",
                          "syn": ["плавка во взвешенном состоянии", "ПВП", "flash smelting",
                                  "взвешенной плавки"]},
    "smelting":          {"name": "плавка", "en": "smelting", "domain": "пирометаллургия",
                          "syn": ["плавки", "плавкой", "smelting"]},
    "converting":        {"name": "конвертирование", "en": "converting", "domain": "пирометаллургия",
                          "syn": ["конвертирования", "converting"]},
    "roasting":          {"name": "обжиг", "en": "roasting", "domain": "пирометаллургия",
                          "syn": ["обжига", "обжигом", "roasting"]},
    "slag_cleaning":     {"name": "обеднение шлаков", "en": "slag cleaning", "domain": "пирометаллургия",
                          "syn": ["обеднения шлаков", "обеднение шлака", "slag cleaning"]},
    "desalination":      {"name": "обессоливание", "en": "desalination", "domain": "водоподготовка",
                          "syn": ["обессоливания", "деминерализация", "desalination", "demineralization"]},
    "reverse_osmosis":   {"name": "обратный осмос", "en": "reverse osmosis", "domain": "водоподготовка",
                          "syn": ["обратного осмоса", "обратноосмотическ", "RO", "reverse osmosis"]},
    "ion_exchange":      {"name": "ионный обмен", "en": "ion exchange", "domain": "водоподготовка",
                          "syn": ["ионного обмена", "ионообменн", "ion exchange", "IX"]},
    "electrodialysis":   {"name": "электродиализ", "en": "electrodialysis", "domain": "водоподготовка",
                          "syn": ["электродиализа", "electrodialysis", "ED"]},
    "evaporation":       {"name": "выпаривание", "en": "evaporation", "domain": "водоподготовка",
                          "syn": ["выпаривания", "выпарка", "evaporation", "дистилляция"]},
    "mine_water_treatment": {"name": "очистка шахтных вод", "en": "mine water treatment", "domain": "экология",
                          "syn": ["очистки шахтных вод", "очистка рудничных вод", "mine water treatment"]},
    "deep_well_injection": {"name": "закачка в глубокие горизонты", "en": "deep well injection", "domain": "экология",
                          "syn": ["закачка шахтных вод", "закачки шахтных вод", "подземное захоронение",
                                  "deep well injection", "закачка в поглощающие горизонты"]},
    "gas_cleaning":      {"name": "очистка газов", "en": "gas cleaning", "domain": "экология",
                          "syn": ["очистки газов", "газоочистка", "газоочистки", "утилизация SO2",
                                  "gas cleaning", "off-gas treatment"]},
    "neutralization":    {"name": "нейтрализация", "en": "neutralization", "domain": "экология",
                          "syn": ["нейтрализации", "известкование", "neutralization"]},
    "crushing":          {"name": "дробление", "en": "crushing", "domain": "рудоподготовка",
                          "syn": ["дробления", "crushing"]},
    "grinding":          {"name": "измельчение", "en": "grinding", "domain": "рудоподготовка",
                          "syn": ["измельчения", "помол", "grinding", "milling"]},
    "backfill":          {"name": "закладка выработанного пространства", "en": "backfill", "domain": "горное дело",
                          "syn": ["закладка", "закладки", "закладочные работы", "закладочных смесей", "backfill"]},
    "drying":            {"name": "сушка", "en": "drying", "domain": "пирометаллургия",
                          "syn": ["сушки", "drying"]},
    "briquetting":       {"name": "брикетирование", "en": "briquetting", "domain": "рудоподготовка",
                          "syn": ["брикетирования", "брикеты", "брикетов", "briquetting"]},
}

EQUIPMENT = {
    "ew_cell":          {"name": "ванна электроэкстракции", "en": "electrowinning cell",
                         "syn": ["ванны электроэкстракции", "электролизная ванна", "электролизных ванн",
                                 "электролизёр", "электролизер", "EW cell", "electrowinning tankhouse"]},
    "diaphragm_cell":   {"name": "диафрагменная ячейка", "en": "diaphragm cell",
                         "syn": ["диафрагменные ячейки", "диафрагменных ячеек", "катодная диафрагма",
                                 "diaphragm cell", "диафрагмой"]},
    "fsf":              {"name": "печь взвешенной плавки", "en": "flash smelting furnace",
                         "syn": ["ПВП", "печи взвешенной плавки", "flash furnace", "flash smelting furnace",
                                 "печь Outokumpu"]},
    "electric_furnace": {"name": "электропечь", "en": "electric furnace",
                         "syn": ["электропечи", "руднотермическая печь", "РТП", "electric furnace"]},
    "converter":        {"name": "конвертер", "en": "converter",
                         "syn": ["конвертера", "конвертеры", "конвертеров", "Пирса-Смита", "Peirce-Smith"]},
    "autoclave":        {"name": "автоклав", "en": "autoclave",
                         "syn": ["автоклава", "автоклавы", "автоклавов", "autoclave"]},
    "ball_mill":        {"name": "шаровая мельница", "en": "ball mill",
                         "syn": ["шаровые мельницы", "шаровых мельниц", "ball mill", "МШЦ", "МШР"]},
    "sag_mill":         {"name": "мельница полусамоизмельчения", "en": "SAG mill",
                         "syn": ["МПСИ", "SAG", "полусамоизмельчения", "AG mill", "ММС"]},
    "flotation_machine": {"name": "флотомашина", "en": "flotation machine",
                         "syn": ["флотомашины", "флотационная машина", "флотационные машины", "flotation cell"]},
    "thickener":        {"name": "сгуститель", "en": "thickener",
                         "syn": ["сгустителя", "сгустители", "thickener"]},
    "filter_press":     {"name": "фильтр-пресс", "en": "filter press",
                         "syn": ["фильтр-пресса", "фильтр-прессы", "filter press"]},
    "scrubber":         {"name": "скруббер", "en": "scrubber",
                         "syn": ["скруббера", "скрубберы", "scrubber"]},
    "esp":              {"name": "электрофильтр", "en": "electrostatic precipitator",
                         "syn": ["электрофильтры", "электрофильтров", "electrostatic precipitator", "ESP"]},
    "ro_membrane":      {"name": "мембранная установка", "en": "membrane unit",
                         "syn": ["мембранные установки", "мембран", "мембранного", "membrane"]},
    "injection_well":   {"name": "поглощающая скважина", "en": "injection well",
                         "syn": ["поглощающие скважины", "нагнетательная скважина", "injection well"]},
}

# Организации/площадки для географической привязки
FACILITIES = {
    "norilsk":     {"name": "Норильский дивизион", "geo": "ru",
                    "syn": ["Норильск", "Норильский", "НМЗ", "Надеждинский", "Талнах", "Медный завод"]},
    "kola":        {"name": "Кольский дивизион", "geo": "ru",
                    "syn": ["Кольская ГМК", "Мончегорск", "Североникель", "Печенганикель", "Заполярный"]},
    "gipronickel": {"name": "Институт Гипроникель", "geo": "ru",
                    "syn": ["Гипроникель", "Гипроникеля"]},
    "harjavalta":  {"name": "Harjavalta", "geo": "foreign", "syn": ["Харьявалта", "Harjavalta"]},
    "jinchuan":    {"name": "Jinchuan", "geo": "foreign", "syn": ["Цзиньчуань", "Jinchuan"]},
    "vale":        {"name": "Vale", "geo": "foreign", "syn": ["Vale", "Вале", "INCO", "Sudbury", "Садбери"]},
    "glencore":    {"name": "Glencore", "geo": "foreign", "syn": ["Glencore", "Xstrata", "Nikkelverk"]},
    "bhp":         {"name": "BHP", "geo": "foreign", "syn": ["BHP", "Billiton"]},
    "sherritt":    {"name": "Sherritt", "geo": "foreign", "syn": ["Sherritt", "Moa Bay", "Моа"]},
    "outotec":     {"name": "Metso Outotec", "geo": "foreign", "syn": ["Outotec", "Outokumpu", "Metso"]},
    "boliden":     {"name": "Boliden", "geo": "foreign", "syn": ["Boliden", "Ronnskar", "Рённшер"]},
    "sumitomo":    {"name": "Sumitomo", "geo": "foreign", "syn": ["Sumitomo", "Ниихама", "Niihama", "CBNC"]},
    "umicore":     {"name": "Umicore", "geo": "foreign", "syn": ["Umicore", "Юмикор", "Hoboken"]},
    "kghm":        {"name": "KGHM", "geo": "foreign", "syn": ["KGHM", "Глогув", "Glogow"]},
}


def all_entities():
    """(entity_type, canon_id, meta) для всех сущностей тезауруса."""
    for cid, m in MATERIALS.items():
        yield "Material", cid, m
    for cid, m in PROCESSES.items():
        yield "Process", cid, m
    for cid, m in EQUIPMENT.items():
        yield "Equipment", cid, m
    for cid, m in FACILITIES.items():
        yield "Facility", cid, m


def build_matcher():
    """Компилирует споттер: список (regex, entity_type, canon_id).
    Синонимы длиной >=4 — по границе слова; короткие (Ni, Cu) — точная словоформа."""
    import re
    matchers = []
    for etype, cid, meta in all_entities():
        variants = {meta["name"], *(meta.get("syn") or [])}
        if meta.get("en"):
            variants.add(meta["en"])
        pats = []
        for v in sorted(variants, key=len, reverse=True):
            esc = re.escape(v)
            if len(v) <= 3:
                pats.append(rf"(?<![A-Za-zА-Яа-я]){esc}(?![a-zа-я])")
            else:
                pats.append(rf"(?<![A-Za-zА-Яа-я]){esc}")
        rx = re.compile("|".join(pats), re.IGNORECASE if len(min(variants, key=len)) > 3 else 0)
        # короткие символы элементов чувствительны к регистру, длинные — нет
        long_rx = re.compile("|".join(p for v, p in zip(sorted(variants, key=len, reverse=True), pats) if len(v) > 3), re.I) if any(len(v) > 3 for v in variants) else None
        short_rx = re.compile("|".join(p for v, p in zip(sorted(variants, key=len, reverse=True), pats) if len(v) <= 3)) if any(len(v) <= 3 for v in variants) else None
        matchers.append((etype, cid, long_rx, short_rx))
    return matchers


def spot(text: str, matchers=None) -> dict:
    """Возвращает {(etype, cid): count} для документа."""
    if matchers is None:
        matchers = build_matcher()
    hits = {}
    for etype, cid, long_rx, short_rx in matchers:
        n = 0
        if long_rx is not None:
            n += sum(1 for _ in long_rx.finditer(text))
        if short_rx is not None:
            n += sum(1 for _ in short_rx.finditer(text))
        if n:
            hits[(etype, cid)] = n
    return hits

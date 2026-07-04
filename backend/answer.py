# -*- coding: utf-8 -*-
"""Синтез структурированного ответа («литобзор») из результатов поиска.

Принцип верификации: каждое утверждение в ответе — это узел графа
(Claim или Condition) с дословной цитатой и ссылкой на публикацию.
Шаблонный синтез детерминирован; если доступна YandexGPT — она только
переформулирует введение, не добавляя фактов.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from search import name_of
import llm

CONF_BADGE = {"high": "🟢 высокая", "medium": "🟡 средняя", "low": "🔴 низкая"}
GEO_LABEL = {"ru": "🇷🇺 отечественная", "foreign": "🌍 зарубежная",
             "both": "🇷🇺+🌍", "mixed": "🇷🇺+🌍", "unknown": "—"}


def _fmt_constraint(f: dict) -> str:
    v2 = f.get("value2")
    val = f"{f['value']:g}–{v2:g}" if v2 not in (None, -1.0) else f"{f['op']} {f['value']:g}".replace("= ", "")
    return f"{f['param']}{(' (' + f['substance'] + ')') if f.get('substance') else ''}: {val} {f['unit']}"


import re as _re

_NUM_RE = _re.compile(r"\d+(?:[.,]\d+)?")


def _numbers_of(text: str) -> set:
    """Нормализованные числа из текста (для валидации ответа против цитат)."""
    return {n.replace(",", ".").rstrip("0").rstrip(".") for n in _NUM_RE.findall(text)}


def _direct_answer(question: str, claims: list, conds: list,
                   claims_out: list | None = None, period_note: str = "",
                   chunks: list | None = None, docs_meta: dict | None = None) -> str | None:
    """Прямой ответ на вопрос строго из верифицированных фактов графа.

    LLM получает ТОЛЬКО топ-релевантные утверждения и обязана отвечать по ним.
    Если в запрошенном периоде фактов нет — используются ближайшие по годам
    с явной пометкой (обязательный сценарий «за последние N лет» не должен
    заканчиваться пустым «информации нет», когда знания в корпусе есть).
    Валидация: каждое число в ответе LLM должно присутствовать в переданных
    фактах — иначе откат на детерминированный ответ (топ-утверждение дословно).
    """
    top_in = [c for c in claims[:5] if c.get("relevance", 0) > 0]
    top_out = [c for c in (claims_out or [])[:5] if c.get("relevance", 0) > 0]
    # если релевантные знания оказались вне периода — используем и их,
    # явно помечая год каждого факта (лучше честный ответ по 2018 г.,
    # чем пустое «информации нет»)
    best_in = top_in[0]["relevance"] if top_in else 0
    best_out = top_out[0]["relevance"] if top_out else 0
    top = top_in[:5]
    out_used = False
    if top_out and (not top_in or best_out > best_in):
        top = (top_out[:3] + top_in[:3])[:6]
        out_used = True
    if not top:
        top = claims[:3]

    chunk_blob = ""
    docs_meta = docs_meta or {}
    chunks = chunks or []
    # фрагменты текста корпуса подмешиваются, когда утверждений нет или они
    # слабо релевантны вопросу (retrieval из источников, не выдумка LLM)
    if chunks and (not top or max(best_in, best_out) < 15):
        chunk_blob = "\n\n".join(
            f"[Фрагмент из «{docs_meta.get(ch['doc_id'], {}).get('title', ch['doc_id'])[:60]}»]:\n{ch['text'][:900]}"
            for ch in chunks[:2])
    if not top and not conds and not chunk_blob:
        return None

    facts_blob = "\n".join(
        f"- ({c['year'] or 'н/д'}{', ВНЕ запрошенного периода' if out_used and c in top_out else ''}) "
        f"{c['text']} [источник: {c['title'][:60]}, узел {c['id']}]" for c in top)
    cond_blob = "\n".join(f"- {c['param']}: {c['op']} {c['value']:g} {c['unit']} "
                          f"(цитата: «{c['quote']}»)" for c in conds[:5])
    allowed_numbers = _numbers_of(facts_blob + " " + cond_blob + " " + chunk_blob)

    prefix = ""
    if out_used and period_note and not top_in:
        years = sorted({c["year"] for c in top_out if c.get("year")})
        span = f"{years[0]}–{years[-1]}" if years else "другие годы"
        prefix = (f"⚠️ В корпусе нет публикаций по теме {period_note}; "
                  f"ближайшие данные — {span} гг.:\n\n")

    llm_ans = llm.complete(
        "Ты — ассистент карты знаний. Ответь на вопрос СЖАТО (3-6 предложений), "
        "используя ИСКЛЮЧИТЕЛЬНО приведённые факты/фрагменты. Все числа бери дословно. "
        "Правила: (1) для обзорных вопросов сгруппируй решения по типам, а не перечисляй "
        "факты подряд; (2) численные значения в разных масштабах/единицах (л/ч на ячейку, "
        "м³/ч на контур, м³/мин на ванну) НЕ сравнивай напрямую — укажи масштаб каждого; "
        "(3) для фактов с пометкой «ВНЕ запрошенного периода» укажи их год; (4) год факта — "
        "это год публикации источника, а не год события; (5) если каких-то аспектов вопроса "
        "в данных нет (например, экономических показателей) — явно скажи, чего не хватает. "
        "Не добавляй ничего от себя.",
        f"Вопрос: {question}\n\nФакты из графа знаний:\n{facts_blob}\n{cond_blob}\n{chunk_blob}",
        temperature=0.0)
    if llm_ans:
        # верификация: числа ответа обязаны существовать в фактах
        if _numbers_of(llm_ans) <= allowed_numbers:
            return prefix + llm_ans.strip()
    # детерминированный откат: самое релевантное утверждение дословно
    if top:
        c = top[0]
        return (f"{prefix}{c['text']}\n\n<sub>источник: *{c['title'][:80]}* ({c['year'] or 'н/д'}) · "
                f"узел `{c['id']}`</sub>")
    return None


def synthesize(result: dict, docs_meta: dict) -> dict:
    p = result["parsed"]
    md = []

    # --- 0. прямой ответ на вопрос (строго из графа, числа валидированы) ---
    period_note = ""
    if p.get("year_from"):
        period_note = f"за период с {p['year_from']}{(' по ' + str(p['year_to'])) if p.get('year_to') else ''} г."
    direct = _direct_answer(p["text"], result.get("claims", []), result.get("conditions", []),
                            claims_out=result.get("claims_out_of_period"),
                            period_note=period_note,
                            chunks=result.get("chunks"), docs_meta=docs_meta)
    if direct:
        md.append("## ✅ Прямой ответ\n")
        md.append(direct)
        md.append("")

    # --- 1. интерпретация запроса (прозрачность для пользователя) ---
    md.append("## 🔍 Как система поняла запрос\n")
    if p["entities"]:
        ents = ", ".join(f"**{name_of(e['type'], e['id'])}** ({e['type']})" for e in p["entities"][:8])
        md.append(f"- Сущности: {ents}")
    if p["numeric"]:
        md.append("- Числовые ограничения (извлечены детерминированно, regex-грамматика):")
        for f in p["numeric"]:
            md.append(f"  - `{_fmt_constraint(f)}` — из «{f['quote']}»")
    if p["geo"]:
        lbl = {"ru": "только отечественная практика", "foreign": "только зарубежная практика",
               "compare": "сравнение: отечественная vs зарубежная"}[p["geo"]]
        md.append(f"- География: {lbl}")
    if p["year_from"]:
        md.append(f"- Период: с {p['year_from']}{(' по ' + str(p['year_to'])) if p['year_to'] else ''} г.")
    # строгое соответствие всем числовым условиям сразу (AND, а не OR)
    n_constr = result.get("n_constraints", 0)
    if n_constr >= 2:
        strict = result.get("strict_docs", [])
        if strict:
            md.append(f"- ✅ Документов, удовлетворяющих **всем {n_constr} числовым условиям "
                      f"одновременно**: {len(strict)} — они подняты в топ выдачи")
        else:
            md.append(f"- ⚠️ Ни один документ не покрывает все {n_constr} числовых условия "
                      f"одновременно — ниже показаны частичные совпадения по каждому условию")
    md.append("")

    # --- 2. подтверждённые утверждения (Claims из графа) ---
    claims = result.get("claims", [])
    if claims:
        md.append("## 📌 Выводы из базы знаний\n")
        by_conf = {"high": [], "medium": [], "low": []}
        for c in claims:
            by_conf.setdefault(c.get("confidence", "medium"), by_conf["medium"]).append(c)
        n_sources = len({c["doc_id"] for c in claims})
        md.append(f"*{len(claims)} утверждений-кандидатов из {n_sources} источников, "
                  f"ранжированы по релевантности (прямой ответ опирается на верхние); "
                  f"каждое — узел графа с дословной цитатой.*\n")
        for conf in ("high", "medium", "low"):
            for c in by_conf[conf][:12]:
                geo = GEO_LABEL.get(c.get("geo", "unknown"), "—")
                quote = (c.get("quote") or "").strip()
                quote_part = f" · цитата: «{quote[:90]}…»" if quote else ""
                md.append(f"- {c['text']}  \n"
                          f"  <sub>достоверность: {CONF_BADGE[conf]} · {geo} · "
                          f"источник: *{c['title'][:80]}* ({c['year'] or 'н/д'}) · "
                          f"узел `{c['id']}`{quote_part}</sub>")
        md.append("")

    # --- 3. числовые данные (Conditions — 100% верифицированы string-match) ---
    conds = result.get("conditions", [])
    if conds:
        md.append("## 🔢 Числовые данные из источников\n")
        md.append("*Каждое значение дословно верифицировано в тексте источника "
                  "(галлюцинации исключены by design).*\n")
        md.append("| Параметр | Значение | Цитата | Источник |")
        md.append("|---|---|---|---|")
        seen = set()
        for c in conds[:15]:
            key = (c["quote"], c["doc_id"])
            if key in seen:
                continue
            seen.add(key)
            md.append(f"| {_fmt_constraint(c)} | {c['op']} {c['value']:g}"
                      f"{('–' + format(c['value2'], 'g')) if c.get('value2') not in (None, -1.0) else ''} {c['unit']} "
                      f"| «{c['quote']}» | {c['title'][:55]} |")
        md.append("")

    # --- 4. источники ---
    pubs = result.get("publications", [])
    if pubs:
        md.append("## 📚 Источники (ранжированы)\n")
        for i, pub in enumerate(pubs[:10], 1):
            geo = GEO_LABEL.get(pub["geo_hint"], "—")
            md.append(f"{i}. **{pub['title'][:90]}** — {pub['year'] or 'н/д'} · {geo} · "
                      f"релевантность {pub['score']:.0f} · `{pub['id']}`")
        md.append("")

    # --- 4а. знания вне запрошенного периода (не теряем, а честно помечаем) ---
    claims_out = result.get("claims_out_of_period") or []
    if claims_out and p.get("year_from"):
        md.append("## ⏳ Релевантные знания вне запрошенного периода\n")
        md.append(f"*Запрошен период с {p['year_from']} г.; ниже — более ранние "
                  f"публикации по теме из корпуса.*\n")
        for c in claims_out[:5]:
            md.append(f"- ({c['year'] or 'н/д'}) {c['text'][:200]}  \n"
                      f"  <sub>источник: *{c['title'][:70]}* · узел `{c['id']}`</sub>")
        md.append("")

    # --- 4б. эксперты и носители компетенций (требование ТЗ) ---
    experts = result.get("experts") or []
    if experts:
        md.append("## 👥 Эксперты и носители компетенций по теме\n")
        for ex in experts[:8]:
            aff = f" — {ex['aff']}" if ex.get("aff") else ""
            md.append(f"- **{ex['name']}**{aff}  \n  <sub>{ex.get('via','')}</sub>")
        md.append("")

    # --- 5. консенсус / разногласия ---
    disagreements = _find_disagreements(conds)
    if disagreements:
        md.append("## ⚠️ Кандидаты в разногласия\n")
        md.append("*Совпадают параметр, вещество и единица, интервалы не пересекаются. "
                  "Режим/оборудование могут различаться — требуется проверка экспертом.*\n")
        for d in disagreements[:5]:
            md.append(f"- **{d['param']}**: источники дают несовпадающие значения — " +
                      "; ".join(f"«{x['quote']}» ({x['title'][:40]})" for x in d["variants"][:3]))
        md.append("")

    # --- 6. пробелы ---
    gaps = _find_gaps(p, claims, conds, pubs)
    if gaps:
        md.append("## 🕳 Пробелы в знаниях\n")
        for g in gaps:
            md.append(f"- {g}")
        md.append("")

    return {"markdown": "\n".join(md),
            "n_claims": len(claims), "n_conditions": len(conds),
            "n_publications": len(pubs), "disagreements": len(disagreements)}


def _find_disagreements(conds: list[dict]) -> list[dict]:
    """Условия с одинаковым (param, unit), но непересекающимися интервалами из разных доков."""
    from search import _bounds
    groups: dict[tuple, list[dict]] = {}
    for c in conds:
        c2 = dict(c)
        if c2.get("value2") == -1.0:
            c2["value2"] = None
        # группируем по (параметр, вещество, единица) — без вещества сравнение
        # разных материалов давало ложные «разногласия»
        groups.setdefault(
            (c["param"], (c.get("substance") or "").lower(), c["unit"].lower()),
            []).append(c2)
    out = []
    for (param, subst, unit), items in groups.items():
        docs = {i["doc_id"] for i in items}
        if len(docs) < 2:
            continue
        bs = [(_bounds(i), i) for i in items]
        conflict = False
        for i in range(len(bs)):
            for j in range(i + 1, len(bs)):
                (lo1, hi1), a = bs[i]
                (lo2, hi2), b = bs[j]
                if a["doc_id"] != b["doc_id"] and (hi1 < lo2 or hi2 < lo1):
                    conflict = True
        if conflict:
            label = f"{param} ({subst})" if subst else param
            out.append({"param": label, "unit": unit, "variants": items})
    return out


def _find_gaps(parsed: dict, claims: list, conds: list, pubs: list) -> list[str]:
    gaps = []
    covered_ents = set()
    for c in claims:
        covered_ents.add(c.get("doc_id"))
    for e in parsed["entities"]:
        ename = name_of(e["type"], e["id"])
        has_claim = any(ename.lower() in (c.get("text", "") or "").lower() for c in claims)
        if not claims or not has_claim:
            if not pubs:
                gaps.append(f"По сущности **{ename}** нет публикаций в базе — кандидат на внешний мониторинг")
    for f in parsed["numeric"]:
        params = f.get("all_params") or [f["param"]]
        matched = [c for c in conds if c["param"] in params]
        if not matched:
            gaps.append(f"Нет численных данных по ограничению `{_fmt_constraint(f)}` — "
                        f"комбинация не изучена в загруженном корпусе")
    if parsed["geo"] == "compare":
        ru_pubs = [p for p in pubs if p["geo_hint"] in ("ru", "mixed")]
        f_pubs = [p for p in pubs if p["geo_hint"] in ("foreign", "mixed")]
        if not ru_pubs:
            gaps.append("Отечественных источников по теме не найдено")
        if not f_pubs:
            gaps.append("Зарубежных источников по теме не найдено")
    return gaps

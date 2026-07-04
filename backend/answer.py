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


def synthesize(result: dict, docs_meta: dict) -> dict:
    p = result["parsed"]
    md = []

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
    md.append("")

    # --- 2. подтверждённые утверждения (Claims из графа) ---
    claims = result.get("claims", [])
    if claims:
        md.append("## 📌 Выводы из базы знаний\n")
        by_conf = {"high": [], "medium": [], "low": []}
        for c in claims:
            by_conf.setdefault(c.get("confidence", "medium"), by_conf["medium"]).append(c)
        n_sources = len({c["doc_id"] for c in claims})
        md.append(f"*{len(claims)} утверждений из {n_sources} источников; "
                  f"каждое — узел графа с дословной цитатой.*\n")
        for conf in ("high", "medium", "low"):
            for c in by_conf[conf][:12]:
                geo = GEO_LABEL.get(c.get("geo", "unknown"), "—")
                md.append(f"- {c['text']}  \n"
                          f"  <sub>достоверность: {CONF_BADGE[conf]} · {geo} · "
                          f"источник: *{c['title'][:80]}* ({c['year'] or 'н/д'}) · узел `{c['id']}`</sub>")
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

    # --- 5. консенсус / разногласия ---
    disagreements = _find_disagreements(conds)
    if disagreements:
        md.append("## ⚠️ Зоны разногласий\n")
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

    intro = None
    if pubs or claims:
        llm_intro = llm.complete(
            "Ты — ассистент карты знаний R&D. Напиши 2-3 предложения введения к структурированному "
            "ответу. НЕ добавляй фактов и чисел, только обобщи тематику. Русский язык.",
            f"Запрос: {p['text']}\nНайдено: {len(pubs)} источников, {len(claims)} утверждений, "
            f"{len(conds)} численных условий.")
        if llm_intro:
            intro = llm_intro.strip()
    header = (intro + "\n\n") if intro else ""
    return {"markdown": header + "\n".join(md),
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
        groups.setdefault((c["param"], c["unit"].lower()), []).append(c2)
    out = []
    for (param, unit), items in groups.items():
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
            out.append({"param": param, "unit": unit, "variants": items})
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
        matched = [c for c in conds if c["param"] == f["param"]]
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

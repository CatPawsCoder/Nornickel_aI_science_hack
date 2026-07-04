# -*- coding: utf-8 -*-
"""Регрессии безопасного прямого ответа без обращения к графу/сети."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import answer  # noqa: E402


def claim(i: int) -> dict:
    return {
        "id": f"doc-cl{i}",
        "text": f"Подтверждённый тезис номер {i}.",
        "quote": f"Дословная цитата для тезиса номер {i}.",
        "title": f"Источник {i}",
        "year": 2020 + i,
        "geo": "foreign",
        "relevance": 100 - i,
    }


def main() -> None:
    claims = [claim(i) for i in range(1, 7)]
    calls = []
    original = answer.llm.complete
    try:
        # Заведомо несуществующее в фактах число заставляет валидатор выбрать fallback.
        def invalid(*args, **kwargs):
            calls.append((args, kwargs))
            return "Неподтверждённое значение 987654321."

        answer.llm.complete = invalid
        out = answer._direct_answer(
            "Литературный обзор технологии", claims, [], docs_meta={})
        assert len(calls) == 1, "при отклонении ответа нельзя повторно вызывать LLM"
        assert out and out.count("узел `doc-cl") == 5, out
        assert "Подтверждённые факты из корпуса" in out

        calls.clear()
        out = answer._direct_answer(
            "Какие способы закачки применялись?", claims, [], docs_meta={},
            missing_intent=["закачка в глубокие горизонты"])
        assert not calls, "для известного пробела корпуса LLM вызываться не должна"
        assert out and "не найдены прямые сведения" in out
        assert "Смежные материалы (не являются прямым ответом)" in out
        assert out.count("узел `doc-cl") == 4, out
    finally:
        answer.llm.complete = original
    print("answer fallback: 2/2 ok")


if __name__ == "__main__":
    main()

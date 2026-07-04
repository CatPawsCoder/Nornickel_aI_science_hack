# -*- coding: utf-8 -*-
"""LLM-клиент: абстракция провайдера.

Провайдеры:
  yandex  — YandexGPT через Yandex AI Studio (ключ кейса).
            На момент разработки роль ai.languageModels.user не выдана (403),
            клиент автоматически пробует доступ и переключается.
  none    — офлайн-режим: синтез из шаблонов + предзапечённый граф.

Yandex Search API у ключа РАБОТАЕТ — используется для мониторинга новых
публикаций (see search_web).
"""
import json
import os
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_env() -> dict:
    env = {}
    p = os.path.join(ROOT, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k] = v
    env.update({k: v for k, v in os.environ.items() if k.startswith("YC_")})
    return env

ENV = _load_env()
API_KEY = ENV.get("YC_API_KEY", "")
FOLDER = ENV.get("YC_FOLDER_ID", "")
OPENROUTER_KEY = ENV.get("OPENROUTER_API_KEY", "").strip('"').strip("'")

_LLM_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
_EMB_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/textEmbedding"
_SEARCH_URL = "https://searchapi.api.cloud.yandex.net/v2/web/searchAsync"
_OPER_URL = "https://operation.api.cloud.yandex.net/operations/"
_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_OPENROUTER_MODEL = "openai/gpt-4o-mini"

_available: bool | None = None
_last_probe = 0.0
_active_provider = "none"  # "yandex" | "openrouter" | "none" — обновляется при первом complete()


def _post(url: str, body: dict, timeout: int = 120) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Authorization": f"Api-Key {API_KEY}", "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def yandex_available(force: bool = False) -> bool:
    """Проба доступа к foundationModels (кэш 5 мин)."""
    global _available, _last_probe
    now = time.time()
    if not force and _available is not None and now - _last_probe < 300:
        return _available
    _last_probe = now
    try:
        _post(_LLM_URL, {
            "modelUri": f"gpt://{FOLDER}/yandexgpt-lite/latest",
            "completionOptions": {"temperature": 0, "maxTokens": 5},
            "messages": [{"role": "user", "text": "ping"}]}, timeout=20)
        _available = True
    except Exception:
        _available = False
    return _available


def _openrouter_complete(system: str, user: str, temperature: float, max_tokens: int) -> str | None:
    if not OPENROUTER_KEY:
        return None
    try:
        req = urllib.request.Request(
            _OPENROUTER_URL,
            data=json.dumps({
                "model": _OPENROUTER_MODEL,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ]}).encode(),
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}",
                     "Content-Type": "application/json"})
        r = json.loads(urllib.request.urlopen(req, timeout=60).read())
        return r["choices"][0]["message"]["content"]
    except Exception:
        return None


def complete(system: str, user: str, model: str = "yandexgpt",
             temperature: float = 0.1, max_tokens: int = 4000) -> str | None:
    """Возвращает текст или None, если ни один провайдер не доступен (офлайн-режим).
    Порядок: YandexGPT (ключ кейса) -> OpenRouter (fallback) -> None."""
    global _active_provider
    if yandex_available():
        try:
            r = _post(_LLM_URL, {
                "modelUri": f"gpt://{FOLDER}/{model}/latest",
                "completionOptions": {"temperature": temperature, "maxTokens": max_tokens},
                "messages": [
                    {"role": "system", "text": system},
                    {"role": "user", "text": user},
                ]})
            _active_provider = "yandex"
            return r["result"]["alternatives"][0]["message"]["text"]
        except Exception:
            pass
    text = _openrouter_complete(system, user, temperature, max_tokens)
    if text is not None:
        _active_provider = "openrouter"
        return text
    _active_provider = "none"
    return None


def active_provider() -> str:
    return _active_provider


def any_llm_available() -> bool:
    return yandex_available() or bool(OPENROUTER_KEY)


def embed(text: str, kind: str = "doc") -> list[float] | None:
    if not yandex_available():
        return None
    model = "text-search-doc" if kind == "doc" else "text-search-query"
    try:
        r = _post(_EMB_URL, {"modelUri": f"emb://{FOLDER}/{model}/latest", "text": text[:8000]})
        return r["embedding"]
    except Exception:
        return None


def search_web(query: str, timeout_s: int = 30) -> list[dict]:
    """Yandex Search API (работает у ключа кейса): поиск новых публикаций.
    Возвращает [{title, url, snippet}]."""
    try:
        op = _post(_SEARCH_URL, {
            "query": {"searchType": "SEARCH_TYPE_RU", "queryText": query},
            "folderId": FOLDER})
        op_id = op["id"]
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            req = urllib.request.Request(_OPER_URL + op_id,
                headers={"Authorization": f"Api-Key {API_KEY}"})
            st = json.loads(urllib.request.urlopen(req, timeout=20).read())
            if st.get("done"):
                import base64
                import re as _re
                raw = base64.b64decode(st["response"]["rawData"]).decode("utf-8", "ignore")
                items = []
                for m in _re.finditer(
                        r"<doc[^>]*>.*?<url>(.*?)</url>.*?<title>(.*?)</title>(.*?)</doc>",
                        raw, _re.S):
                    url, title, rest = m.group(1), m.group(2), m.group(3)
                    sn = _re.search(r"<passage>(.*?)</passage>", rest, _re.S)
                    title = _re.sub(r"<.*?>", "", title)
                    snippet = _re.sub(r"<.*?>", "", sn.group(1)) if sn else ""
                    items.append({"title": title, "url": url, "snippet": snippet})
                return items[:10]
            time.sleep(1.5)
    except Exception:
        pass
    return []


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print("yandex LLM available:", yandex_available(force=True))
    res = search_web("электроэкстракция никеля скорость циркуляции католита")
    for r in res[:3]:
        print("-", r["title"][:80], "|", r["url"][:60])

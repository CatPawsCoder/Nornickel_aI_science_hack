# -*- coding: utf-8 -*-
"""Тест GigaChat: OAuth-обмен authorization key -> access token -> completion."""
import base64, json, ssl, sys, urllib.request, uuid
sys.stdout.reconfigure(encoding="utf-8")

# ключ читается из .env (в репозиторий не попадает)
import os
_env = {}
_envp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(_envp):
    for _l in open(_envp, encoding="utf-8"):
        if "=" in _l and not _l.strip().startswith("#"):
            _k, _v = _l.strip().split("=", 1)
            _env[_k] = _v
AUTH_KEY = _env.get("GIGACHAT_AUTH_KEY", "")

# что зашито в ключе
dec = base64.b64decode(AUTH_KEY).decode()
print("decoded:", dec)
cid, secret = dec.split(":")
print("client_id:", cid)

# Штатная проверка TLS против официального корневого сертификата НУЦ Минцифры
ctx = ssl.create_default_context(cafile="certs/russiantrustedca.pem")

def get_token(scope):
    body = f"scope={scope}".encode()
    req = urllib.request.Request(
        "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": str(uuid.uuid4()),
            "Authorization": f"Basic {AUTH_KEY}",
        })
    r = json.loads(urllib.request.urlopen(req, context=ctx, timeout=30).read())
    return r

for scope in ("GIGACHAT_API_PERS", "GIGACHAT_API_B2B", "GIGACHAT_API_CORP"):
    try:
        r = get_token(scope)
        tok = r.get("access_token", "")
        print(f"[{scope}] OK token len={len(tok)} expires={r.get('expires_at')}")
        # test completion
        payload = json.dumps({
            "model": "GigaChat",
            "messages": [{"role": "user", "content": "Ответь одним словом: столица России?"}],
            "temperature": 0.1,
        }).encode()
        req2 = urllib.request.Request(
            "https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json",
                     "Authorization": f"Bearer {tok}"})
        r2 = json.loads(urllib.request.urlopen(req2, context=ctx, timeout=60).read())
        print("  completion:", r2["choices"][0]["message"]["content"][:80])
        break
    except Exception as e:
        print(f"[{scope}] FAIL:", repr(e)[:200])

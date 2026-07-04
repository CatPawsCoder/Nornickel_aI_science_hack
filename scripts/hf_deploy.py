# -*- coding: utf-8 -*-
"""Деплой на Hugging Face Space: создание репо + загрузка staging-папки."""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

from huggingface_hub import HfApi

TOKEN = os.environ.get("HF_TOKEN", "")
REPO = "catpawws/AI_Science_Hack"
STAGE = r"C:\Users\Asus ROG\nauchny-klubok\hf-space-stage"

api = HfApi(token=TOKEN)
print("whoami:", api.whoami()["name"])

url = api.create_repo(repo_id=REPO, repo_type="space", space_sdk="docker", exist_ok=True)
print("space:", url)

print("uploading folder (LFS для больших файлов)...")
api.upload_folder(
    repo_id=REPO, repo_type="space",
    folder_path=STAGE,
    commit_message="Научный клубок: код + предсобранные данные (граф Kùzu + FTS5-индекс)",
)
print("UPLOAD DONE")

info = api.space_info(REPO)
print("stage:", info.runtime.stage if info.runtime else "?")
print(f"URL: https://huggingface.co/spaces/{REPO}")
sub = REPO.replace("/", "-").replace("_", "-").lower()
print(f"Direct: https://{sub}.hf.space")

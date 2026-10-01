"""Prompt 檔案載入（prompt 與程式碼分開管理）。

規格（Stage 3 spec，2026-10-01 使用者要求 prompt 獨立管理）
========================================================

prompt 放在 ``backend/app/llm/prompts/<name>/`` 底下：
- ``system.md``：系統指令（規則）
- ``user.md``：使用者訊息模板，以 ``$變數`` 標示要填入的內容（``string.Template`` 語法，
  因為內容含 JSON，不用 ``{}`` 格式避免衝突）

``load_prompt(name, prompts_dir=PROMPTS_DIR) -> PromptTemplate``
- ``version``：system.md + user.md 內容的 sha256 前 12 碼。修改 prompt 檔案版本就自動改變，
  不需手動維護版號；報告會記錄此版本，事後可追溯哪個 prompt 產生哪份報告
- 資料夾或檔案不存在 → FileNotFoundError

``PromptTemplate.render_user(**values) -> str``：模板中的變數必須全部提供，缺少 → KeyError
（避免把未填的 ``$facts`` 原樣送給 LLM）
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from string import Template

from pydantic import BaseModel

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


class PromptTemplate(BaseModel):
    name: str
    system: str
    user_template: str
    version: str

    def render_user(self, **values: str) -> str:
        return Template(self.user_template).substitute(values)


def load_prompt(name: str, prompts_dir: Path = PROMPTS_DIR) -> PromptTemplate:
    folder = Path(prompts_dir) / name
    system = (folder / "system.md").read_text(encoding="utf-8")
    user_template = (folder / "user.md").read_text(encoding="utf-8")
    version = hashlib.sha256(f"{system}\0{user_template}".encode("utf-8")).hexdigest()[:12]
    return PromptTemplate(name=name, system=system, user_template=user_template, version=version)

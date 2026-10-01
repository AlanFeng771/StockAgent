"""Prompt 檔案載入（prompt 與程式碼分開管理）。

規格（Stage 3 spec，2026-10-01 使用者要求 prompt 獨立管理）
========================================================

prompt 放在 ``backend/app/llm/prompts/<name>/`` 底下，每個 ``.md`` 檔一個部分：
- ``system.md``（必要）：系統指令（規則）
- ``user.md``（必要）：使用者訊息模板
- 其他 ``*.md``（選用）：額外模板，以檔名（不含副檔名）為名稱，例如 ``repair.md``（自動修正）
模板以 ``$變數`` 標示要填入的內容（``string.Template`` 語法，因為內容含 JSON，不用 ``{}`` 避免衝突）。

``load_prompt(name, prompts_dir=PROMPTS_DIR) -> PromptTemplate``
- ``version``：資料夾內所有 .md（依檔名排序，含檔名）內容的 sha256 前 12 碼。修改任一 prompt 檔案
  版本就自動改變，不需手動維護版號；報告會記錄此版本，事後可追溯哪個 prompt 產生哪份報告
- 資料夾、system.md 或 user.md 不存在 → FileNotFoundError

``PromptTemplate.render(name, **values)`` / ``render_user(**values)``：模板中的變數必須全部提供，
缺少 → KeyError（避免把未填的 ``$facts`` 原樣送給 LLM）；模板名稱不存在 → KeyError
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
    templates: dict[str, str]
    version: str

    @property
    def user_template(self) -> str:
        return self.templates["user"]

    def has(self, template: str) -> bool:
        return template in self.templates

    def render(self, template: str, **values: str) -> str:
        return Template(self.templates[template]).substitute(values)

    def render_user(self, **values: str) -> str:
        return self.render("user", **values)


def load_prompt(name: str, prompts_dir: Path = PROMPTS_DIR) -> PromptTemplate:
    folder = Path(prompts_dir) / name
    system = (folder / "system.md").read_text(encoding="utf-8")
    (folder / "user.md").stat()  # user.md 為必要檔案，不存在時丟 FileNotFoundError

    digest = hashlib.sha256()
    templates: dict[str, str] = {}
    for path in sorted(folder.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        digest.update(path.name.encode("utf-8") + b"\0" + text.encode("utf-8") + b"\0")
        if path.stem != "system":
            templates[path.stem] = text
    return PromptTemplate(name=name, system=system, templates=templates, version=digest.hexdigest()[:12])

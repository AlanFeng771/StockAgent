from __future__ import annotations

import pytest

from backend.app.llm.prompt_templates import load_prompt


def write_prompt(base, name="demo", system="系統規則", user="請分析 $stock_label：$facts"):
    folder = base / name
    folder.mkdir(parents=True)
    (folder / "system.md").write_text(system, encoding="utf-8")
    (folder / "user.md").write_text(user, encoding="utf-8")
    return folder


def test_loads_system_and_user_from_files(tmp_path):
    write_prompt(tmp_path)

    prompt = load_prompt("demo", tmp_path)

    assert prompt.name == "demo"
    assert prompt.system == "系統規則"
    assert prompt.render_user(stock_label="2330 台積電", facts='{"a": 1}') == '請分析 2330 台積電：{"a": 1}'


def test_version_changes_when_prompt_text_changes(tmp_path):
    write_prompt(tmp_path)
    first = load_prompt("demo", tmp_path)
    (tmp_path / "demo" / "system.md").write_text("系統規則 v2", encoding="utf-8")
    second = load_prompt("demo", tmp_path)

    assert len(first.version) == 12
    assert first.version != second.version


def test_version_is_stable_for_same_content(tmp_path):
    write_prompt(tmp_path)

    assert load_prompt("demo", tmp_path).version == load_prompt("demo", tmp_path).version


def test_missing_variable_raises(tmp_path):
    write_prompt(tmp_path)

    with pytest.raises(KeyError):
        load_prompt("demo", tmp_path).render_user(stock_label="2330")


def test_json_braces_in_values_are_not_interpreted(tmp_path):
    write_prompt(tmp_path, user="$facts")

    assert load_prompt("demo", tmp_path).render_user(facts='{"x": "$y"}') == '{"x": "$y"}'


def test_missing_prompt_folder_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_prompt("not_exist", tmp_path)


def test_real_stock_report_prompt_loads():
    prompt = load_prompt("stock_report")

    assert "只能根據事實清單推論" in prompt.system
    assert "$facts" in prompt.user_template

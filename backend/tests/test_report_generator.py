from __future__ import annotations

import json
from types import SimpleNamespace

import openai
import pytest
from openai.lib._pydantic import to_strict_json_schema

from backend.app.config import Settings
from backend.app.llm.report_generator import build_facts, generate_report
from backend.app.llm.report_schema import PricePoint, StockReport
from backend.app.signals.signal_builder import build_stock_signals
from backend.tests.test_signal_builder import make_data


@pytest.fixture(scope="module")
def signals():
    return build_stock_signals("2330", make_data())


def settings(api_key="sk-test"):
    return Settings(_env_file=None, openai_api_key=api_key, openai_model="gpt-4o", openai_temperature=0.2)


def allowed_price(signals):
    return signals.price_levels.supports[0].price


def make_report(signals, entry_price=None, **overrides):
    """預設是一份價格關係一致的報告：買點取最近支撐、停損取最低支撐、目標取最高壓力。"""
    entry = entry_price if entry_price is not None else allowed_price(signals)
    levels = signals.price_levels
    data = {
        "summary": "測試摘要", "overall_bias": "neutral",
        "entry_points": [PricePoint(price=entry, basis="測試", condition="測試")],
        "exit_points": [],
        "target_price": PricePoint(price=levels.resistances[-1].price, basis="t", condition="t") if levels else None,
        "target_price_reason": "r",
        "stop_loss": PricePoint(price=levels.supports[-1].price, basis="s", condition="s") if levels else None,
        "stop_loss_reason": "r",
        "holding_period": "swing", "holding_period_reason": "r", "long_term_suitable": False,
        "long_term_reason": "r", "risks": ["風險"], "rationale": [], "confidence": "low",
        "confidence_reason": "r", "data_limitations": [],
    }
    data.update(overrides)
    return StockReport(**data)


class FakeClient:
    """模擬 openai client 的 chat.completions.parse，記錄呼叫參數。"""

    def __init__(self, parsed=None, refusal=None, error=None, usage=(1200, 300)):
        self.calls = []
        self._parsed, self._refusal, self._error, self._usage = parsed, refusal, error, usage
        self.chat = SimpleNamespace(completions=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        message = SimpleNamespace(parsed=self._parsed, refusal=self._refusal, content=None)
        usage = None if self._usage is None else SimpleNamespace(prompt_tokens=self._usage[0], completion_tokens=self._usage[1])
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")], usage=usage)


# ---------------------------------------------------------------------------
# schema 與事實清單
# ---------------------------------------------------------------------------

def test_report_schema_is_valid_for_structured_outputs():
    schema = to_strict_json_schema(StockReport)

    assert set(schema["required"]) == set(StockReport.model_fields)


def test_facts_exclude_news_links_and_are_compact(signals):
    facts = build_facts(signals)

    parsed = json.loads(facts)
    assert parsed["news"], "測試資料應有新聞"
    assert all("link" not in item for item in parsed["news"])
    assert "\n" not in facts
    assert "台積電" in facts  # 股票名稱
    assert "price_levels" in parsed


# ---------------------------------------------------------------------------
# 呼叫與結果
# ---------------------------------------------------------------------------

def test_success_returns_report_with_traceability(signals):
    report = make_report(signals)
    client = FakeClient(parsed=report)

    result = generate_report(signals, client=client, settings=settings())

    assert result.llm_status == "success"
    assert result.report == report
    assert result.error is None
    assert result.warnings == []
    assert result.model == "gpt-4o"
    assert len(result.prompt_version) == 12
    assert (result.prompt_tokens, result.completion_tokens) == (1200, 300)


def test_request_contains_system_prompt_facts_and_schema(signals):
    client = FakeClient(parsed=make_report(signals))

    generate_report(signals, client=client, settings=settings())

    call = client.calls[0]
    assert call["model"] == "gpt-4o"
    assert call["response_format"] is StockReport
    assert call["temperature"] == 0.2
    system, user = call["messages"]
    assert system["role"] == "system" and "只能根據事實清單推論" in system["content"]
    assert user["role"] == "user"
    assert "2330 台積電" in user["content"]
    assert build_facts(signals) in user["content"]
    assert "$facts" not in user["content"]


@pytest.mark.parametrize("api_key", [None, "", "your_openai_api_key_here"])
def test_missing_or_placeholder_key_is_pending_without_calling(signals, api_key):
    client = FakeClient(parsed=make_report(signals))

    result = generate_report(signals, client=client, settings=settings(api_key=api_key))

    assert result.llm_status == "pending"
    assert result.report is None
    assert "OPENAI_API_KEY" in result.error
    assert client.calls == []


@pytest.mark.parametrize("error", [
    openai.APIConnectionError(request=None),
    RuntimeError("unexpected"),
])
def test_api_errors_become_failed_without_raising(signals, error):
    result = generate_report(signals, client=FakeClient(error=error), settings=settings())

    assert result.llm_status == "failed"
    assert result.report is None
    assert result.error


def test_refusal_is_failed(signals):
    result = generate_report(signals, client=FakeClient(refusal="I can't help with that."), settings=settings())

    assert result.llm_status == "failed"
    assert "拒" in result.error


def test_unparsed_output_is_failed(signals):
    result = generate_report(signals, client=FakeClient(parsed=None), settings=settings())

    assert result.llm_status == "failed"


def test_missing_usage_is_none(signals):
    result = generate_report(signals, client=FakeClient(parsed=make_report(signals), usage=None), settings=settings())

    assert result.prompt_tokens is None


# ---------------------------------------------------------------------------
# 價格驗證
# ---------------------------------------------------------------------------

def test_price_not_in_levels_produces_warning(signals):
    bad = make_report(signals, entry_price=12345.67, stop_loss=PricePoint(price=1.11, basis="x", condition="x"))

    result = generate_report(signals, client=FakeClient(parsed=bad), settings=settings())

    assert result.llm_status == "success"
    not_in_list = [w for w in result.warnings if "不在提供的價位清單" in w]
    assert len(not_in_list) == 2
    assert "12345.67" in not_in_list[0]


def test_close_chart_price_and_fill_price_are_allowed(signals):
    levels = signals.price_levels
    allowed = [levels.close] + [lv.chart_price for lv in levels.supports + levels.resistances if lv.chart_price]
    report = make_report(signals, entry_points=[PricePoint(price=p, basis="x", condition="x") for p in allowed])

    result = generate_report(signals, client=FakeClient(parsed=report), settings=settings())

    assert result.warnings == []


def test_prices_without_price_levels_warn():
    no_levels = build_stock_signals("2330", make_data(prices=make_data().prices.tail(30)))
    report = StockReport.model_validate(make_report(build_stock_signals("2330", make_data())).model_dump())

    result = generate_report(no_levels, client=FakeClient(parsed=report), settings=settings())

    assert result.warnings and "價位清單" in result.warnings[0]


# ---------------------------------------------------------------------------
# 價格關係檢查（實測 2454：有買點卻沒給停損/目標價，且賣點在現價下方的語意矛盾）
# ---------------------------------------------------------------------------

def point(price):
    return PricePoint(price=price, basis="測試", condition="測試")


def levels_of(signals):
    lv = signals.price_levels
    return lv.close, [x.price for x in lv.supports], [x.price for x in lv.resistances]


def test_entry_without_stop_loss_warns_when_support_below_exists(signals):
    close, supports, resistances = levels_of(signals)
    report = make_report(signals, entry_price=supports[0], target_price=point(resistances[0]), stop_loss=None)

    result = generate_report(signals, client=FakeClient(parsed=report), settings=settings())

    assert any("未給停損價" in w for w in result.warnings)


def test_missing_target_warns_when_resistance_above_exists(signals):
    close, supports, resistances = levels_of(signals)
    report = make_report(signals, entry_price=supports[0], stop_loss=point(supports[-1]), target_price=None)

    result = generate_report(signals, client=FakeClient(parsed=report), settings=settings())

    assert any("未給目標價" in w for w in result.warnings)


def test_consistent_report_has_no_warnings(signals):
    close, supports, resistances = levels_of(signals)
    report = make_report(
        signals, entry_price=supports[0], stop_loss=point(supports[-1]), target_price=point(resistances[-1]),
        exit_points=[point(resistances[0])],
    )

    result = generate_report(signals, client=FakeClient(parsed=report), settings=settings())

    assert result.warnings == []


def test_price_relationship_warnings(signals):
    close, supports, resistances = levels_of(signals)
    report = make_report(
        signals, entry_price=supports[-1],
        stop_loss=point(supports[0]),          # 停損高於買點
        target_price=point(supports[1]),       # 目標價低於現價
        exit_points=[point(supports[0])],      # 賣點低於現價
    )

    warnings = generate_report(signals, client=FakeClient(parsed=report), settings=settings()).warnings

    assert any("停損價" in w and "不低於" in w for w in warnings)
    assert any("目標價" in w and "不高於現價" in w for w in warnings)
    assert any("賣點" in w and "不高於現價" in w for w in warnings)


def test_no_entry_and_not_recommended_does_not_require_target_or_stop(signals):
    report = make_report(signals, entry_points=[], holding_period="not_recommended")

    result = generate_report(signals, client=FakeClient(parsed=report), settings=settings())

    assert result.warnings == []


def test_reason_fields_exist_in_schema():
    assert {"target_price_reason", "stop_loss_reason"} <= set(StockReport.model_fields)

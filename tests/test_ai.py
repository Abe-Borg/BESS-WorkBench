import json
import logging

from bess_workbench.ai.assistant import Assistant, ErrorEvent, ProposalEvent
from bess_workbench.ai.client import AITransientError, MockClient, StreamDone, TextDelta, ToolCall, call_with_retries
from bess_workbench.ai.drafting import draft_narrative, draft_rfi_text
from bess_workbench.ai.intake import apply_accepted, extraction_from_text, flatten_for_review
from bess_workbench.ai.keystore import Keystore, MemoryKeyring
from bess_workbench.ai.pricing import Usage, estimate_cost
from bess_workbench.ai.redact import register_secret, scrub
from bess_workbench.ai.request import build_chat_kwargs, build_extract_kwargs
from bess_workbench.ai.tools import TOOL_SPECS, apply_tool, get_path, set_path
from bess_workbench.controller import ProjectController
from bess_workbench.ruleset import load_rules
from bess_workbench.sample_data import build_sample_project


def _controller():
    rules = load_rules()
    return ProjectController(build_sample_project(rules), rules)


def test_request_caches_system_and_rules_and_has_no_key():
    rules_text = '{"ruleset_id": "demo"}'
    kwargs = build_chat_kwargs(model="claude-sonnet-5-5", rules_text=rules_text, messages=[], tools=TOOL_SPECS)
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kwargs["system"][1]["cache_control"] == {"type": "ephemeral"}
    assert kwargs["system"][1]["text"] == rules_text
    assert "api_key" not in json.dumps(kwargs)
    names = {tool["name"] for tool in kwargs["tools"]}
    assert names == {"get_project", "run_checks", "get_rule", "list_open_items", "add_rfi", "set_input"}
    extract = build_extract_kwargs(model="claude-sonnet-5-5", pdf_base64="QQ==", filename="report.pdf")
    document = extract["messages"][0]["content"][0]
    assert document["type"] == "document"
    assert document["source"]["media_type"] == "application/pdf"
    assert extract["system"][0]["cache_control"]["type"] == "ephemeral"


def test_set_input_is_not_applied_until_approved():
    controller = _controller()
    original = controller.project.sprinklers.hose_gpm
    client = MockClient(
        rounds=[
            [
                ToolCall(id="t1", name="set_input", arguments={"path": "sprinklers.hose_gpm", "value": 250}),
                StreamDone(Usage(input_tokens=20, output_tokens=5), "tool_use"),
            ],
            [TextDelta("Left the hose allowance alone."), StreamDone(Usage(input_tokens=5, output_tokens=4), "end_turn")],
        ]
    )
    assistant = Assistant(client, controller, "{}")
    events = list(assistant.send("change the hose", lambda _proposal: False))
    assert any(isinstance(event, ProposalEvent) for event in events)
    assert controller.project.sprinklers.hose_gpm == original
    assert "User rejected" in json.dumps(client.calls[1]["messages"])


def test_approved_set_input_recomputes():
    controller = _controller()
    client = MockClient(
        rounds=[
            [
                ToolCall(id="t1", name="set_input", arguments={"path": "sprinklers.hose_gpm", "value": 250}),
                StreamDone(Usage(), "tool_use"),
            ],
            [TextDelta("Hose is 250."), StreamDone(Usage(output_tokens=3), "end_turn")],
        ]
    )
    assistant = Assistant(client, controller, "{}")
    list(assistant.send("set hose", lambda _proposal: True))
    assert controller.project.sprinklers.hose_gpm == 250
    assert assistant.usage.output_tokens == 3


def test_readonly_tool_round_trip():
    controller = _controller()
    client = MockClient(
        rounds=[
            [ToolCall(id="t1", name="get_rule", arguments={"rule_id": "FP-FA-600"}), StreamDone(Usage(), "tool_use")],
            [TextDelta("See FP-FA-600, IFC 2024 Table 1207.5."), StreamDone(Usage(), "end_turn")],
        ]
    )
    assistant = Assistant(client, controller, load_rules().model_dump_json())
    text = []
    for event in assistant.send("what is the cap", lambda _proposal: False):
        if isinstance(event, TextDelta):
            text.append(event.text)
    assert "FP-FA-600" in "".join(text)
    tool_result = client.calls[1]["messages"][-1]["content"][0]["content"]
    assert "1207.5" in tool_result
    assert controller.project.sprinklers.hose_gpm == 100


def test_add_rfi_preview_and_apply():
    controller = _controller()
    before = len(controller.project.rfis)
    updated, message = apply_tool(
        controller.project,
        "add_rfi",
        {"title": "Confirm shaft", "text": "Show the shaft rating.", "assignee": "Mech"},
    )
    assert len(updated.rfis) == before + 1
    assert updated.rfis[-1].source == "ai"
    assert "Added" in message
    data = controller.project.model_dump(mode="json")
    set_path(data, "rooms[0].area_sf", 900)
    assert get_path(data, "rooms[0].area_sf") == 900


def test_retries_then_succeeds():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise AITransientError("overloaded")
        return "ok"

    assert call_with_retries(flaky, sleep=lambda _seconds: None) == "ok"
    assert calls["n"] == 3


def test_scrub_keeps_keys_out_of_logs(caplog):
    secret = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz"
    register_secret("super-secret-key-value")
    logger = logging.getLogger("bess_workbench.ai.test")
    with caplog.at_level(logging.INFO, logger="bess_workbench"):
        logger.info("failed %s and %s", secret, "super-secret-key-value")
    assert secret not in caplog.text
    assert "super-secret-key-value" not in caplog.text
    assert "[REDACTED]" in caplog.text
    assert scrub(secret) == "[REDACTED]"


def test_keystore_prefers_keyring_and_hides_the_key(monkeypatch):
    backend = MemoryKeyring()
    store = Keystore(backend)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key-12345678")
    status = store.status()
    assert status["source"] == "environment"
    assert "env-key-12345678" not in status["hint"]
    assert status["hint"].endswith("5678). The full key is not shown.")
    store.save("ring-key-abcdefgh")
    status = store.status()
    assert status["source"] == "keyring"
    assert "ring-key-abcdefgh" not in status["hint"]
    store.clear()
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert store.status()["present"] is False


def test_intake_round_trip_tags_source_and_page():
    raw = """```json
    {"gases": [{"name": "H2", "mass_g": 12.5, "lfl_vol_pct": 4, "page": 14}],
     "kwh_entries": [{"room_hint": "UPS BESS Room 2", "kwh": 140, "page": 3}],
     "monitoring_only": true, "add_alternate": false, "notes": []}
    ```"""
    extraction = extraction_from_text(raw, "synthetic-9540a.pdf")
    fields = flatten_for_review(extraction)
    keys = [field.key for field in fields]
    controller = _controller()
    updated = apply_accepted(controller.project, extraction, keys, "synthetic-9540a.pdf")
    assert updated.gas.monitoring_only is True
    assert updated.ess_groups[1].kwh == 140
    assert updated.gas.release_species[0].mass_g == 12.5
    assert updated.gas.release_species[0].page == 14
    assert any(item.source_document == "synthetic-9540a.pdf" and item.page == 14 for item in updated.provenance)


def test_draft_helpers_use_the_mock_and_do_not_touch_checks():
    controller = _controller()
    before = [item.status for item in controller.analysis.checks]
    client = MockClient(text="Please confirm the shaft rating. Rule FA-DOOR.")
    text, _usage = draft_rfi_text(client, controller, controller.project.rfis[0])
    assert "FA-DOOR" in text or "shaft" in text.lower()
    narrative, _usage = draft_narrative(client, controller)
    assert narrative
    assert [item.status for item in controller.analysis.checks] == before


def test_cost_estimate_is_labeled_math():
    usage = Usage(input_tokens=1_000_000, output_tokens=0, cache_read_tokens=1_000_000, cache_write_tokens=0)
    assert estimate_cost("claude-sonnet-5-5", usage) == 3.0 + 0.30


def test_assistant_surfaces_errors():
    class Boom:
        model = "mock"

        def complete_stream(self, _kwargs):
            raise AITransientError("nope")
            yield

    events = list(Assistant(Boom(), _controller(), "{}").send("hi", lambda _proposal: False))
    assert any(isinstance(event, ErrorEvent) for event in events)

"""LLM paths with a fake Anthropic client - no network."""
from types import SimpleNamespace as NS

import core.llm as llm
from agents.orchestrator import OrchestratorAgent
from core.schemas import AppSpec, PipelineSpec, ReviewReport


class FakeMessages:
    def __init__(self):
        self.calls = 0
        self.parse_inputs = []

    def create(self, **kw):
        self.calls += 1
        usage = NS(input_tokens=1, output_tokens=1)
        if self.calls == 1:  # model calls only one of the required tools
            block = NS(type="tool_use", id="t1", name="render_library_core", input={})
            return NS(stop_reason="tool_use", content=[block], usage=usage)
        return NS(stop_reason="end_turn", content=[NS(type="text", text="done")], usage=usage)

    def parse(self, **kw):
        self.parse_inputs.append(kw)
        fmt = kw["output_format"]
        parsed = ReviewReport(summary="ok") if fmt is ReviewReport else PipelineSpec(apps=[AppSpec(name="a", tech="go")])
        return NS(parsed_output=parsed, stop_reason="end_turn", usage=NS(input_tokens=1, output_tokens=1))


def test_full_run_with_fake_model_fills_gaps(monkeypatch):
    fake = NS(messages=FakeMessages())
    monkeypatch.setattr(llm, "_client", lambda: fake)
    result = OrchestratorAgent().run(request="go service to ecr", review=True)
    files = result["bundle"].files
    assert "jenkins/a/Jenkinsfile.validation" in files  # produced by fallback after the model skipped it
    assert "shared-library/vars/platformConfig.groovy" in files
    assert result["validator_issues"] == []
    assert result["review"].summary == "ok"
    assert any(r["filled_by_fallback"] for r in result["agent_reports"])


def test_diagram_is_sent_to_the_vision_model(monkeypatch, tmp_path):
    img = tmp_path / "arch.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake = NS(messages=FakeMessages())
    monkeypatch.setattr(llm, "_client", lambda: fake)
    OrchestratorAgent().run(request="from diagram", diagram_path=str(img), use_llm=True, review=False)
    first = fake.messages.parse_inputs[0]
    assert first["model"] == llm.settings.MODEL_VISION
    assert first["messages"][0]["content"][0]["type"] == "image"


def test_tool_errors_are_returned_to_model(monkeypatch):
    seen = {}

    class M(FakeMessages):
        def create(self, **kw):
            self.calls += 1
            usage = NS(input_tokens=1, output_tokens=1)
            if self.calls == 1:
                block = NS(type="tool_use", id="t1", name="nope", input={})
                return NS(stop_reason="tool_use", content=[block], usage=usage)
            seen["result"] = kw["messages"][-1]["content"][0]
            return NS(stop_reason="end_turn", content=[NS(type="text", text="x")], usage=usage)

    fake = NS(messages=M())
    monkeypatch.setattr(llm, "_client", lambda: fake)
    llm.run_with_tools("m", "s", "t", [])
    assert seen["result"]["is_error"] is True

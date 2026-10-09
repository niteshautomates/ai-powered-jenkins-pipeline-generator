# core/llm.py
"""Thin Anthropic wrapper: per-task model routing, structured output, tool loop, Langfuse tracing."""

import base64
import json
import logging
import mimetypes
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar

import anthropic
from pydantic import BaseModel

from config import settings

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

# --- Langfuse (optional) -----------------------------------------------------------------
# Langfuse v2 reads LANGFUSE_* from the environment (loaded by config.settings via dotenv).
# Without keys, `observe` becomes a no-op so the generator runs untraced.
try:
    if not settings.langfuse_enabled:
        raise ImportError("langfuse keys not configured")
    from langfuse.decorators import langfuse_context, observe
except Exception:  # pragma: no cover - exercised when keys are absent

    def observe(*dargs: Any, **dkwargs: Any):  # type: ignore[no-redef]
        if len(dargs) == 1 and callable(dargs[0]) and not dkwargs:
            return dargs[0]
        return lambda fn: fn

    class _NoopContext:
        def update_current_observation(self, **_: Any) -> None: ...
        def update_current_trace(self, **_: Any) -> None: ...
        def flush(self) -> None: ...

    langfuse_context = _NoopContext()  # type: ignore[assignment]


def _client() -> anthropic.Anthropic:
    settings.validate()
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


def _usage(resp: Any) -> Dict[str, int]:
    u = resp.usage
    return {"input": u.input_tokens, "output": u.output_tokens}


def image_block(path: str) -> Dict[str, Any]:
    """Base64 image content block for multi-modal inputs (architecture diagrams, screenshots)."""
    media_type = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


def _text(resp: Any) -> str:
    return "".join(b.text for b in resp.content if b.type == "text")


@observe(as_type="generation")
def parse(model: str, system: str, content: Any, schema: Type[T], max_tokens: Optional[int] = None) -> T:
    """Single call returning a validated pydantic object (structured outputs)."""
    resp = _client().messages.parse(
        model=model,
        max_tokens=max_tokens or settings.MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": content}],
        output_format=schema,
    )
    langfuse_context.update_current_observation(
        model=model, usage={"input": resp.usage.input_tokens, "output": resp.usage.output_tokens}
    )
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise RuntimeError(f"{model} returned no parsable output (stop_reason={resp.stop_reason})")
    return resp.parsed_output


class Tool:
    """A narrowly-scoped capability exposed to one agent."""

    def __init__(self, name: str, description: str, input_schema: Dict[str, Any], fn: Callable[..., str]):
        self.name, self.description, self.input_schema, self.fn = name, description, input_schema, fn

    def spec(self) -> Dict[str, Any]:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


@observe(as_type="generation")
def _create(model: str, system: str, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Any:
    resp = _client().messages.create(
        model=model,
        max_tokens=settings.MAX_TOKENS,
        system=system,
        messages=messages,
        tools=tools,
    )
    langfuse_context.update_current_observation(model=model, usage=_usage(resp))
    return resp


@observe()
def run_with_tools(model: str, system: str, task: str, tools: List[Tool]) -> str:
    """Manual tool loop: model picks tools, we run them, results go back in one user message."""
    registry = {t.name: t for t in tools}
    specs = [t.spec() for t in tools]
    messages: List[Dict[str, Any]] = [{"role": "user", "content": task}]

    for _ in range(settings.MAX_TOOL_ROUNDS):
        resp = _create(model, system, messages, specs)
        if resp.stop_reason == "refusal":
            raise RuntimeError(f"{model} refused the request")
        if resp.stop_reason == "max_tokens":
            raise RuntimeError("Model hit max_tokens mid-response; raise MAX_TOKENS")
        # Echo content back unchanged (thinking blocks must be preserved on the same model)
        messages.append({"role": "assistant", "content": resp.content})
        calls = [b for b in resp.content if b.type == "tool_use"]
        if resp.stop_reason != "tool_use" or not calls:
            return _text(resp)

        results = []
        for call in calls:
            tool = registry.get(call.name)
            try:
                if tool is None:
                    raise KeyError(f"unknown tool {call.name}")
                out, is_error = tool.fn(**call.input), False
            except Exception as e:  # report to the model so it can correct its arguments
                logger.warning("tool %s failed: %s", call.name, e)
                out, is_error = f"{type(e).__name__}: {e}", True
            results.append(
                {"type": "tool_result", "tool_use_id": call.id, "content": str(out), "is_error": is_error}
            )
        messages.append({"role": "user", "content": results})

    raise RuntimeError(f"Tool loop exceeded {settings.MAX_TOOL_ROUNDS} rounds")


def flush() -> None:
    langfuse_context.flush()

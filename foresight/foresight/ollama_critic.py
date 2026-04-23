"""OllamaCritic — calls a locally-served Ollama model (default
``nail-reason:v3.1``) to critique a Plan.

The critic asks the model to return JSON in a stable schema:

    {
      "summary": "<one paragraph>",
      "risks": [
        {"severity": "low|medium|high|critical",
         "title": "<short>",
         "detail": "<longer>",
         "affects_step": <int|null>,
         "mitigation": "<short>"}
      ]
    }

If the model does not produce valid JSON we run a fallback regex extractor
that pulls out lines like ``- [HIGH] title :: mitigation``. Failing both,
we return a single ``CRITICAL`` risk titled "critic-output-unparseable" so
the caller never silently loses a defence-in-depth signal.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from .critique import Critique, Risk, RiskSeverity
from .plan import Plan


DEFAULT_BASE_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("NAIL_FORESIGHT_MODEL", "nail-reason:v3.1")
DEFAULT_TIMEOUT_S = float(os.environ.get("NAIL_FORESIGHT_TIMEOUT", "60"))


SYSTEM_PROMPT = (
    "You are a security-risk critic for autonomous agents. Given a plan "
    "(goal + ordered tool calls) and a world snapshot, identify concrete "
    "failure modes BEFORE the plan executes. Be specific and concise. "
    "Return STRICT JSON ONLY, matching exactly this schema and nothing else:\n"
    '{"summary": "<one paragraph>", '
    '"risks": [{"severity": "low|medium|high|critical", "title": "<short>", '
    '"detail": "<longer>", "affects_step": <int or null>, '
    '"mitigation": "<short>"}]}'
)


class OllamaError(RuntimeError):
    """Network / protocol failure talking to Ollama."""


def _build_user_prompt(plan: Plan, world: dict) -> str:
    return (
        "PLAN\n----\n"
        f"{plan.render()}\n\n"
        "WORLD SNAPSHOT (relevant facts available before execution)\n"
        f"{json.dumps(world or {}, indent=2)}\n\n"
        "Return the JSON now."
    )


class OllamaCritic:
    def __init__(self, *, model: str = DEFAULT_MODEL,
                 base_url: str = DEFAULT_BASE_URL,
                 timeout_s: float = DEFAULT_TIMEOUT_S,
                 temperature: float = 0.2) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.temperature = temperature

    # ── public ──────────────────────────────────────────────────
    def critique(self, plan: Plan, *,
                 world: dict | None = None) -> Critique:
        raw = self._chat(plan, world or {})
        risks, summary = _parse_response(raw)
        c = Critique(risks=risks, summary=summary,
                     raw_response=raw, model=self.model)
        # Lazy import to avoid a circular at module load.
        from .critic import _emit_critique
        _emit_critique(c, plan)
        return c

    # ── transport ────────────────────────────────────────────────
    def _chat(self, plan: Plan, world: dict) -> str:
        url = f"{self.base_url}/api/chat"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": _build_user_prompt(plan, world)},
            ],
            "stream": False,
            "options": {"temperature": self.temperature},
            "format": "json",
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise OllamaError(f"could not reach Ollama at {url}: {e}") from e
        except json.JSONDecodeError as e:
            raise OllamaError(f"non-JSON response from Ollama: {e}") from e

        msg = (data.get("message") or {}).get("content")
        if not msg:
            raise OllamaError(f"Ollama returned no message content: {data}")
        return str(msg)


# ── parsing ──────────────────────────────────────────────────────────
_VALID_SEVERITY = {s.value for s in RiskSeverity}


def _parse_response(raw: str) -> tuple[list[Risk], str]:
    # 1. Try strict JSON.
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        d = _extract_json_object(raw)

    if isinstance(d, dict) and isinstance(d.get("risks"), list):
        risks = []
        for r in d["risks"]:
            if not isinstance(r, dict):
                continue
            sev = str(r.get("severity", "medium")).lower()
            if sev not in _VALID_SEVERITY:
                sev = "medium"
            try:
                step = int(r["affects_step"]) if r.get("affects_step") is not None else None
            except (ValueError, TypeError):
                step = None
            risks.append(Risk(
                severity=RiskSeverity(sev),
                title=str(r.get("title", "(untitled risk)"))[:200],
                detail=str(r.get("detail", "")),
                affects_step=step,
                mitigation=str(r.get("mitigation", "")),
            ))
        summary = str(d.get("summary", ""))[:1000]
        return risks, summary

    # 2. Regex fallback: lines like `- [HIGH] title :: mitigation`
    risks = list(_regex_extract(raw))
    if risks:
        return risks, "(parsed via regex fallback)"

    # 3. Total parse failure → emit a CRITICAL risk so the verdict is HOLD/REJECT.
    return [Risk(
        severity=RiskSeverity.CRITICAL,
        title="critic-output-unparseable",
        detail=f"could not parse model response (first 200 chars): "
               f"{raw[:200]!r}",
        mitigation="Treat as HOLD; ask a human; possibly switch critic model.",
    )], "(unparseable response from critic)"


_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json_object(s: str) -> Any:
    m = _OBJ_RE.search(s)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


_LINE_RE = re.compile(
    r"""^[\s\-\*\d\.\)]*               # bullet/number prefix
        \[?\s*(?P<sev>critical|high|medium|low)\s*\]? # severity tag
        \s*[:\-]?\s*
        (?P<title>[^\:\n]{3,120})
        (?:\s*::\s*(?P<mit>.+))?       # optional ' :: mitigation'
        \s*$""",
    re.IGNORECASE | re.VERBOSE,
)


def _regex_extract(raw: str):
    for line in raw.splitlines():
        m = _LINE_RE.match(line.strip())
        if not m:
            continue
        yield Risk(
            severity=RiskSeverity(m.group("sev").lower()),
            title=m.group("title").strip(),
            mitigation=(m.group("mit") or "").strip(),
        )

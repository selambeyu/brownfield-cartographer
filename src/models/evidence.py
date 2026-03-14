from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class EvidenceRef(BaseModel):
    path: str
    line_start: int | None = None
    line_end: int | None = None


class TraceEvent(BaseModel):
    ts: str
    run_id: str
    event: Literal["run_start", "run_end", "phase_start", "phase_end", "error", "metric"]
    phase: str | None = None
    message: str | None = None
    error_code: str | None = None
    recoverable: bool | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class AgentErrorEnvelope(BaseModel):
    phase: str
    error_type: str
    message: str
    recoverable: bool = True
    details: dict[str, Any] = Field(default_factory=dict)


def make_error_envelope(
    *,
    phase: str,
    error: Exception,
    recoverable: bool = True,
    details: dict[str, Any] | None = None,
) -> AgentErrorEnvelope:
    return AgentErrorEnvelope(
        phase=phase,
        error_type=type(error).__name__,
        message=str(error),
        recoverable=recoverable,
        details=details or {},
    )


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def write_trace_event(trace_path: str, event: TraceEvent) -> None:
    Path(trace_path).parent.mkdir(parents=True, exist_ok=True)
    with open(trace_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event.model_dump(mode="json"), ensure_ascii=False) + "\n")


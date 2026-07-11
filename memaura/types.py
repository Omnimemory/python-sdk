from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional


RoleV1 = Literal["user", "assistant", "system"]


@dataclass(frozen=True)
class CanonicalAttachmentV1:
    type: str
    name: Optional[str] = None
    truncated: bool = False
    sha256: Optional[str] = None
    ref: Optional[str] = None


@dataclass(frozen=True)
class CanonicalTurnV1:
    turn_id: str
    role: RoleV1
    text: str
    name: Optional[str] = None
    timestamp_iso: Optional[str] = None
    refer_list: Optional[List[str]] = None
    attachments: Optional[List[CanonicalAttachmentV1]] = None
    meta: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class JobStatusV1:
    job_id: str
    session_id: str
    status: str
    attempts: Optional[Dict[str, int]] = None
    next_retry_at: Optional[str] = None
    last_error: Optional[Dict[str, Any]] = None
    metrics: Optional[Dict[str, Any]] = None

"""omem - Python SDK for omem memory service.

Give your AI agents long-term memory with just two lines of code.

Quick Start:
    >>> from omem import Memory
    >>> 
    >>> mem = Memory(api_key="qbk_xxx")  # That's it!
    >>> 
    >>> # Save conversation
    >>> mem.add("conv-001", [
    ...     {"role": "user", "content": "Hello"},
    ...     {"role": "assistant", "content": "Hi!"},
    ... ])
    >>> 
    >>> # Search memories
    >>> result = mem.search("greeting")
    >>> if result:
    ...     print(result.to_prompt())

For more information, see: https://github.com/VisMemo/python-sdk
"""

from .memory import Memory, Conversation
from .models import (
    MemoryItem,
    SearchResult,
    Entity,
    Event,
    Evidence,
    EventContext,
    ExtractedKnowledge,
    AddResult,
)
from .client import (
    MemoryClient,
    SessionBuffer,
    CommitHandle,
    RetryConfig,
    OmemClientError,
    OmemHttpError,
    OmemAuthError,
    OmemForbiddenError,
    OmemRateLimitError,
    OmemQuotaExceededError,
    OmemPayloadTooLargeError,
    OmemValidationError,
    OmemServerError,
)
from .types import CanonicalAttachmentV1, CanonicalTurnV1, JobStatusV1, SessionStatusV1

# Version
__version__ = "1.0.0"

__all__ = [
    # Version
    "__version__",
    # High-level API (recommended for most users)
    "Memory",
    "Conversation",
    "MemoryItem",
    "SearchResult",
    "Entity",
    "Event",
    "Evidence",
    "EventContext",
    "ExtractedKnowledge",
    "AddResult",
    # Error types
    "OmemClientError",
    "OmemHttpError",
    "OmemAuthError",
    "OmemForbiddenError",
    "OmemRateLimitError",
    "OmemQuotaExceededError",
    "OmemPayloadTooLargeError",
    "OmemValidationError",
    "OmemServerError",
    # Low-level API (for advanced use cases)
    "MemoryClient",
    "SessionBuffer",
    "CommitHandle",
    "RetryConfig",
    "CanonicalAttachmentV1",
    "CanonicalTurnV1",
    "JobStatusV1",
    "SessionStatusV1",
]

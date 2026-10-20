"""MemAura Python SDK.

Give your AI agents long-term memory with just two lines of code.

Quick Start:
    >>> from memaura import Memory
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

For more information, see the MemAura SDK documentation.
"""

from .memory import Memory, Conversation
from .v4 import (
    MemoryV4,
    V4Card,
    V4Episode,
    V4Job,
    V4JobTimeoutError,
    V4RetrievalResult,
)
from .models import (
    MemoryItem,
    EvidenceDetail,
    SearchResult,
    AddResult,
)
from .client import (
    MemAuraClientError,
    MemAuraHttpError,
    MemAuraAuthError,
    MemAuraForbiddenError,
    MemAuraRateLimitError,
    MemAuraQuotaExceededError,
    MemAuraPayloadTooLargeError,
    MemAuraValidationError,
    MemAuraServerError,
)

# Version
__version__ = "0.1.0"

__all__ = [
    # Version
    "__version__",
    # High-level API (recommended for most users)
    "Memory",
    "Conversation",
    "MemoryV4",
    "V4Card",
    "V4Episode",
    "V4Job",
    "V4JobTimeoutError",
    "V4RetrievalResult",
    "MemoryItem",
    "EvidenceDetail",
    "SearchResult",
    "AddResult",
    # Error types
    "MemAuraClientError",
    "MemAuraHttpError",
    "MemAuraAuthError",
    "MemAuraForbiddenError",
    "MemAuraRateLimitError",
    "MemAuraQuotaExceededError",
    "MemAuraPayloadTooLargeError",
    "MemAuraValidationError",
    "MemAuraServerError",
]

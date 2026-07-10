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

For more information, see: https://github.com/Omnimemory/python-sdk
"""

from .memory import Memory, Conversation
from .models import (
    MemoryItem,
    SearchResult,
    AddResult,
)
from .client import (
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

# Version
__version__ = "2.0.0"

__all__ = [
    # Version
    "__version__",
    # High-level API (recommended for most users)
    "Memory",
    "Conversation",
    "MemoryItem",
    "SearchResult",
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
]

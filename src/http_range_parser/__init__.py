"""HTTP Range Parser — parse Range and Content-Range headers into absolute byte intervals."""

from .core import RangeSpec, ContentRangeSpec, RangeParseError

__all__ = ["RangeSpec", "ContentRangeSpec", "RangeParseError"]

"""Core parser for HTTP Range and Content-Range header fields.

Scope and design decisions
-------------------------
This library parses exactly two RFC 9110 header field syntaxes:

    Range: bytes=START-END[, START-END]*            (RFC 9110 §14.107)
    Content-Range: bytes START-END/TOTAL            (RFC 9110 §14.50)

Only the "bytes" range unit is supported. The spec allows other range units
but they are never used in practice for byte ranges, and supporting them
would make the API vaguer without any real benefit.

Parsing is strict: malformed input raises RangeParseError instead of returning
a partial or best-effort result. The spec is permissive about how servers
should react to bad ranges, but a *parser* library that silently coerces junk
into something usable makes every downstream bug harder to find. Fail loud,
let callers decide.

"Absolute interval" means (start, end) in 0-indexed inclusive byte offsets.
Resolving against a resource length is a separate, explicit step so the
parser itself has no hidden state about the resource.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple


# The only range unit this library recognises. RFC 9110 §14.107 lets the
# grammar accept arbitrary units, but byte-range serving is all anyone uses.
# Hard-coding keeps the parsed representation concrete and simple.
_RANGE_UNIT = "bytes"


class RangeParseError(ValueError):
    """Raised when a Range or Content-Range header cannot be parsed.

    Inherits ValueError so callers that only catch ValueError still work.
    """


@dataclass(frozen=True)
class RangeSpec:
    """A parsed Range header.

    Attributes
    ----------
    unit : str
        The range unit, always "bytes" for this library.
    ranges : tuple
        Tuple of (start, end) tuples. start is an int, or None for a
        suffix range (bytes=LAST-N). end is an int, or None for an
        open-ended prefix range (bytes=START-). The latter is non-standard
        but tolerated by real servers, so we keep the information rather
        than dropping it.
    """

    unit: str
    ranges: Tuple[Tuple[Optional[int], Optional[int]], ...]

    def resolve(self, length: int) -> List[Tuple[int, int]]:
        """Resolve every range against a concrete resource length.

        Returns a list of absolute, inclusive (start, end) intervals.

        length must be a non-negative int. A zero-length resource yields an
        empty list — there are no bytes to serve, so no satisfiable range.

        Suffix ranges (start is None) mean "the last N bytes", clamped to
        the whole resource when N exceeds length. Prefix ranges (end is None)
        mean "from START to the end of the resource".
        """
        if not isinstance(length, int) or isinstance(length, bool):
            raise TypeError("length must be int")
        if length < 0:
            raise ValueError("length must be non-negative")

        resolved: List[Tuple[int, int]] = []
        last_index = length - 1

        for start, end in self.ranges:
            if start is None:
                # Suffix range: last `end` bytes.
                n = end  # type: ignore[assignment]
                if n <= 0:
                    # bytes=-0 is a legal but unsatisfiable edge: asking for
                    # the last 0 bytes. Skip it rather than emit a 0-length
                    # interval, which would mislead callers who index by [0].
                    continue
                s = max(0, length - n)
                e = last_index
                resolved.append((s, e))
            elif end is None:
                # Prefix range: START- (non-standard but tolerated).
                if start < 0:
                    continue
                if start > last_index:
                    # Start beyond the resource → unsatisfiable for this range.
                    continue
                resolved.append((start, last_index))
            else:
                # Fully specified range START-END.
                if start > end or start > last_index:
                    continue
                s = start
                e = min(end, last_index)
                resolved.append((s, e))

        return resolved


def parse_range(header: str) -> RangeSpec:
    """Parse a Range header value into a RangeSpec.

    Strict: any deviation from the bytes= grammar raises RangeParseError.
    """
    if not isinstance(header, str):
        raise TypeError("header must be str")

    # RFC 9110 allows OWS (optional whitespace) around the value but real
    # servers trim leading/trailing spaces, so we do too. Interior whitespace
    # around the unit and '=' is rejected because the spec grammar for the
    # range unit and the '=' does not permit it, and tolerating it would hide
    # bugs in upstream code that constructs these headers.
    header = header.strip()
    if not header:
        raise RangeParseError("empty Range header")

    eq = header.find("=")
    if eq == -1:
        raise RangeParseError("missing '=' in Range header")

    unit = header[:eq].strip()
    if unit.lower() != _RANGE_UNIT:
        raise RangeParseError(f"unsupported range unit: {unit!r}")
    # Keep the canonical lowercase form so downstream comparisons are trivial.
    unit = _RANGE_UNIT

    rest = header[eq + 1:]
    if not rest:
        raise RangeParseError("no ranges after '='")

    parts = rest.split(",")
    ranges: List[Tuple[Optional[int], Optional[int]]] = []
    for part in parts:
        # A single internal space around the dash is common and harmless, but
        # the spec grammar does not allow it. We strip it rather than reject
        # because nearly every client gets this wrong and rejecting would make
        # the parser useless in practice. This is the one deliberate leniency.
        part = part.strip()
        if not part:
            raise RangeParseError("empty range specifier")

        dash = part.find("-")
        if dash == -1:
            raise RangeParseError(f"missing '-' in range: {part!r}")

        start_s = part[:dash].strip()
        end_s = part[dash + 1:].strip()

        if not start_s and not end_s:
            raise RangeParseError(f"range has no bounds: {part!r}")
        if not start_s:
            # Suffix range: -N. End holds N.
            if not end_s.isdigit():
                raise RangeParseError(f"invalid suffix length: {end_s!r}")
            ranges.append((None, int(end_s)))
            continue
        if not end_s:
            # Prefix range: START-. Non-standard, tolerated.
            if not start_s.isdigit():
                raise RangeParseError(f"invalid start: {start_s!r}")
            ranges.append((int(start_s), None))
            continue

        if not start_s.isdigit() or not end_s.isdigit():
            raise RangeParseError(f"non-numeric range bounds: {part!r}")

        s = int(start_s)
        e = int(end_s)
        if s > e:
            raise RangeParseError(f"start > end in range: {part!r}")
        ranges.append((s, e))

    if not ranges:
        raise RangeParseError("no ranges parsed")

    return RangeSpec(unit=unit, ranges=tuple(ranges))


@dataclass(frozen=True)
class ContentRangeSpec:
    """A parsed Content-Range header.

    Attributes
    ----------
    unit : str
        Always "bytes".
    start : int or None
        Inclusive start byte. None when the header is a length-only form
        (bytes */TOTAL) indicating an unsatisfiable range.
    end : int or None
        Inclusive end byte. None alongside start when length-only.
    length : int or None
        Total resource length in bytes, or None when unknown (bytes START-END/*).
    """

    unit: str
    start: Optional[int]
    end: Optional[int]
    length: Optional[int]


def parse_content_range(header: str) -> ContentRangeSpec:
    """Parse a Content-Range header value into a ContentRangeSpec.

    Recognised forms (RFC 9110 §14.50):
        bytes START-END/TOTAL
        bytes START-END/*
        bytes */TOTAL
    """
    if not isinstance(header, str):
        raise TypeError("header must be str")

    header = header.strip()
    if not header:
        raise RangeParseError("empty Content-Range header")

    slash = header.rfind("/")
    if slash == -1:
        raise RangeParseError("missing '/' in Content-Range header")

    left = header[:slash].strip()
    length_s = header[slash + 1:].strip()

    # Split unit from the interval on the first space, as the grammar requires.
    sp = left.find(" ")
    if sp == -1:
        raise RangeParseError("missing space between unit and interval")

    unit = left[:sp].strip().lower()
    if unit != _RANGE_UNIT:
        raise RangeParseError(f"unsupported range unit: {unit!r}")
    interval = left[sp + 1:].strip()

    # Length side.
    if length_s == "*":
        length: Optional[int] = None
    else:
        if not length_s.isdigit():
            raise RangeParseError(f"invalid length: {length_s!r}")
        length = int(length_s)

    # Interval side.
    if interval == "*":
        # bytes */TOTAL — unsatisfiable range, total is given.
        if length is None:
            raise RangeParseError("both interval and length are '*' is invalid")
        return ContentRangeSpec(unit=_RANGE_UNIT, start=None, end=None, length=length)

    dash = interval.find("-")
    if dash == -1:
        raise RangeParseError(f"missing '-' in interval: {interval!r}")

    start_s = interval[:dash].strip()
    end_s = interval[dash + 1:].strip()
    if not start_s.isdigit() or not end_s.isdigit():
        raise RangeParseError(f"non-numeric interval bounds: {interval!r}")

    s = int(start_s)
    e = int(end_s)
    if s > e:
        raise RangeParseError(f"start > end: {interval!r}")

    return ContentRangeSpec(unit=_RANGE_UNIT, start=s, end=e, length=length)

# HTTP Range Parser

Parses HTTP `Range` and `Content-Range` header field syntax into absolute byte intervals. Standard library only, no third-party dependencies.

## Usage

```python
from http_range_parser.core import parse_range, parse_content_range

spec = parse_range("bytes=0-499,-200")
absolute = spec.resolve(length=1000)
# [(0, 499), (800, 999)]

cr = parse_content_range("bytes 0-499/1000")
# ContentRangeSpec(unit="bytes", start=0, end=499, length=1000)
```

## Why this exists

Real HTTP range serving has three concerns that are easy to conflate: parsing the header syntax, validating the result against a resource length, and deciding the wire response. This library does only the first two and stops. It returns plain tuples and dataclasses so callers can build whatever response semantics they need without the parser imposing a policy.

The trade-off: parsing is strict. Malformed input raises `RangeParseError` rather than coercing. The one deliberate leniency is whitespace inside range bounds (`bytes=0 - 99`), because nearly every client emits it and rejecting it would make the parser useless in practice.

## Edge cases you will hit

- `bytes=-0` (last zero bytes) is syntactically legal but unsatisfiable. `resolve` skips it rather than emitting a zero-length interval, which would mislead callers that index by `[0]`.
- `bytes=9500-` (open-ended prefix) is non-standard but tolerated by real servers. The parser keeps it as `(9500, None)` and `resolve` closes it against the resource length.
- Only the `bytes` range unit is supported. Any other unit raises `RangeParseError`.
- `resolve` rejects `bool` for the length argument even though `bool` subclasses `int`, because accepting it would be a silent footgun.

## Running the tests

```
PYTHONPATH=src python -m unittest discover -s tests
```

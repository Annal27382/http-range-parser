import unittest

from http_range_parser import RangeSpec, ContentRangeSpec, RangeParseError
from http_range_parser.core import parse_range, parse_content_range


class ParseRangeTests(unittest.TestCase):
    def test_single_range(self):
        spec = parse_range("bytes=0-99")
        self.assertEqual(spec.unit, "bytes")
        self.assertEqual(spec.ranges, ((0, 99),))

    def test_multiple_ranges(self):
        spec = parse_range("bytes=0-9,20-29,100-199")
        self.assertEqual(spec.ranges, ((0, 9), (20, 29), (100, 199)))

    def test_suffix_range(self):
        spec = parse_range("bytes=-500")
        self.assertEqual(spec.ranges, ((None, 500),))

    def test_prefix_range_tolerated(self):
        # Non-standard but widely emitted by real clients.
        spec = parse_range("bytes=9500-")
        self.assertEqual(spec.ranges, ((9500, None),))

    def test_mixed_ranges(self):
        spec = parse_range("bytes=0-9,-5,100-")
        self.assertEqual(spec.ranges, ((0, 9), (None, 5), (100, None)))

    def test_internal_space_stripped(self):
        spec = parse_range("bytes=0 - 99, 200 - 299")
        self.assertEqual(spec.ranges, ((0, 99), (200, 299)))

    def test_empty_header_raises(self):
        with self.assertRaises(RangeParseError):
            parse_range("")

    def test_missing_equals_raises(self):
        with self.assertRaises(RangeParseError):
            parse_range("bytes0-99")

    def test_unsupported_unit_raises(self):
        with self.assertRaises(RangeParseError):
            parse_range("items=0-99")

    def test_start_greater_than_end_raises(self):
        with self.assertRaises(RangeParseError):
            parse_range("bytes=100-50")

    def test_non_numeric_raises(self):
        with self.assertRaises(RangeParseError):
            parse_range("bytes=abc-99")

    def test_empty_subrange_raises(self):
        with self.assertRaises(RangeParseError):
            parse_range("bytes=0-9,,20-29")

    def test_no_bounds_raises(self):
        with self.assertRaises(RangeParseError):
            parse_range("bytes=-")

    def test_non_str_raises(self):
        with self.assertRaises(TypeError):
            parse_range(123)  # type: ignore[arg-type]


class ResolveRangeTests(unittest.TestCase):
    def test_resolve_basic(self):
        spec = parse_range("bytes=0-99")
        self.assertEqual(spec.resolve(1000), [(0, 99)])

    def test_resolve_clamps_end(self):
        spec = parse_range("bytes=0-9999")
        self.assertEqual(spec.resolve(1000), [(0, 999)])

    def test_resolve_suffix(self):
        spec = parse_range("bytes=-500")
        self.assertEqual(spec.resolve(1000), [(500, 999)])

    def test_resolve_suffix_larger_than_resource(self):
        spec = parse_range("bytes=-5000")
        self.assertEqual(spec.resolve(1000), [(0, 999)])

    def test_resolve_prefix(self):
        spec = parse_range("bytes=9500-")
        self.assertEqual(spec.resolve(10000), [(9500, 9999)])

    def test_resolve_start_beyond_length_skipped(self):
        spec = parse_range("bytes=5000-5999")
        self.assertEqual(spec.resolve(1000), [])

    def test_resolve_zero_length(self):
        spec = parse_range("bytes=0-0")
        self.assertEqual(spec.resolve(0), [])

    def test_resolve_negative_length_raises(self):
        spec = parse_range("bytes=0-0")
        with self.assertRaises(ValueError):
            spec.resolve(-1)

    def test_resolve_non_int_length_raises(self):
        spec = parse_range("bytes=0-0")
        with self.assertRaises(TypeError):
            spec.resolve("1000")  # type: ignore[arg-type]

    def test_resolve_bool_length_rejected(self):
        # bool is a subclass of int; accepting it would be a silent footgun.
        spec = parse_range("bytes=0-0")
        with self.assertRaises(TypeError):
            spec.resolve(True)  # type: ignore[arg-type]

    def test_resolve_suffix_zero_skipped(self):
        # bytes=-0 asks for the last 0 bytes; unsatisfiable, skip it.
        spec = parse_range("bytes=-0")
        self.assertEqual(spec.resolve(1000), [])


class ParseContentRangeTests(unittest.TestCase):
    def test_full_form(self):
        cr = parse_content_range("bytes 0-499/1000")
        self.assertEqual(cr, ContentRangeSpec(unit="bytes", start=0, end=499, length=1000))

    def test_unknown_length(self):
        cr = parse_content_range("bytes 0-499/*")
        self.assertEqual(cr, ContentRangeSpec(unit="bytes", start=0, end=499, length=None))

    def test_unsatisfiable_form(self):
        cr = parse_content_range("bytes */1000")
        self.assertEqual(cr, ContentRangeSpec(unit="bytes", start=None, end=None, length=1000))

    def test_invalid_unit_raises(self):
        with self.assertRaises(RangeParseError):
            parse_content_range("items 0-499/1000")

    def test_missing_slash_raises(self):
        with self.assertRaises(RangeParseError):
            parse_content_range("bytes 0-499")

    def test_missing_space_raises(self):
        with self.assertRaises(RangeParseError):
            parse_content_range("bytes0-499/1000")

    def test_start_greater_than_end_raises(self):
        with self.assertRaises(RangeParseError):
            parse_content_range("bytes 500-499/1000")

    def test_star_star_raises(self):
        with self.assertRaises(RangeParseError):
            parse_content_range("bytes */*")

    def test_non_numeric_length_raises(self):
        with self.assertRaises(RangeParseError):
            parse_content_range("bytes 0-499/abc")

    def test_empty_header_raises(self):
        with self.assertRaises(RangeParseError):
            parse_content_range("")


if __name__ == "__main__":
    unittest.main()

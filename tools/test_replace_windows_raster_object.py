#!/usr/bin/env python3
"""Regression tests for archive preservation and architecture refusal."""
import struct
import unittest

from replace_windows_raster_object import members, validate_replacement


def obj(machine: int, payload: bytes) -> bytes:
    return struct.pack("<HHI", machine, 1, 0) + payload


def entry(name: str, data: bytes) -> bytes:
    header = f"{name:<16}{0:<12}{0:<6}{0:<6}{'0':<8}{len(data):<10}`\n".encode()
    return header + data + (b"\n" if len(data) % 2 else b"")


class ReplacementTests(unittest.TestCase):
    def setUp(self):
        self.old = obj(0xA641, b"scalar")
        self.vector = obj(0xA641, b"vector")
        self.other = obj(0xA641, b"unrelated")
        self.before = [("core.SkOpts.obj", self.old), ("other.obj", self.other)]
        self.after = [("other.obj", self.other), ("vector.obj", self.vector)]

    def test_windows_long_names_and_special_members(self):
        name = r"obj\src\core\core.SkOpts.obj"
        raw = b"!<arch>\n" + entry("/", b"symbols") + entry("//", name.encode() + b"\0")
        raw += entry("/<ECSYMBOLS>/", b"ec symbols") + entry("/0", self.old)
        self.assertEqual(members(raw), [(name, self.old)])

    def test_truncated_and_invalid_archives_refused(self):
        for data in (b"not an archive", b"!<arch>\nx", b"!<arch>\n" + entry("x/", self.old)[:-2],
                     b"!<arch>\n" + entry("/0", self.old)):
            with self.subTest(data=data), self.assertRaises(ValueError):
                members(data)

    def test_preserved_objects_pass(self):
        validate_replacement(self.before, self.after, "core.SkOpts.obj", self.vector, "arm64ec")

    def test_changed_dropped_duplicated_and_stale_objects_refused(self):
        for after in (self.after[:1], self.after[1:], self.after + self.after[:1],
                      self.after + [("stale.obj", self.old)],
                      [("other.obj", obj(0xA641, b"modified")), self.after[1]]):
            with self.subTest(after=after), self.assertRaises(ValueError):
                validate_replacement(self.before, after, "core.SkOpts.obj", self.vector, "arm64ec")

    def test_native_arm64_cannot_be_relabelled_as_ec(self):
        foreign = obj(0xAA64, b"vector")
        with self.assertRaisesRegex(ValueError, "incompatible COFF"):
            validate_replacement(self.before, [("vector.obj", foreign)], "core.SkOpts.obj",
                                 foreign, "arm64ec")


if __name__ == "__main__":
    unittest.main()

"""hfp_codec reads the codec of a call from a PacketLogger log, made here (no real log)."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import hfp_codec  # noqa: E402


def record(kind: int, payload: bytes, order: str = ">") -> bytes:
    return struct.pack(order + "III", 9 + len(payload), 1, 2) + bytes([kind]) + payload


def acl(text: bytes) -> bytes:  # an ACL packet whose RFCOMM data carries an AT command
    return b"\x0b\x20\x18\x00\x14\x00\x41\x00\x0b\xef\x29" + text + b"\r\x8e"


def link(air_mode: int) -> bytes:  # Synchronous Connection Complete, status 0
    return (bytes([0x2C, 17, 0]) + b"\x01\x00" + b"\xaa" * 6 + bytes([2, 12, 2]) + b"\x3c\x00\x3c\x00"
            + bytes([air_mode]))


def setup(coding: int) -> bytes:  # Enhanced Setup Synchronous Connection: handle, bandwidths, coding
    return struct.pack("<HB", 0x043D, 59) + b"\x01\x00" + struct.pack("<II", 8000, 8000) + bytes([coding]) + b"\0" * 4


def accept(coding: int) -> bytes:  # Enhanced Accept Synchronous Connection: address, bandwidths, coding
    return struct.pack("<HB", 0x043E, 63) + b"\xaa" * 6 + struct.pack("<II", 8000, 8000) + bytes([coding]) + b"\0" * 4


def failed() -> bytes:  # Synchronous Connection Complete with an error status
    return bytes([0x2C, 17, 0x0D]) + b"\0" * 16


class Codec(unittest.TestCase):
    def test_a_wideband_call(self):
        log = b"".join([record(2, acl(b"AT+BRSF=191")), record(3, acl(b"+BRSF: 3943")),
                        record(2, acl(b"AT+BAC=1,2")), record(3, acl(b"+BCS: 2")),
                        record(0, setup(0x05)), record(1, link(3))])
        lines = hfp_codec.verdict(hfp_codec.read(log))
        self.assertIn("codec negotiation: yes", lines[0])
        self.assertIn("codecs the car offers (AT+BAC): CVSD, mSBC", lines)
        self.assertEqual(lines[-1], "verdict: WIDEBAND (mSBC, 16 kHz, about 50-7000 Hz)")

    def test_a_narrowband_car(self):
        log = b"".join([record(2, acl(b"AT+BRSF=63"), "<"), record(3, acl(b"+BRSF: 3943"), "<"),
                        record(1, link(2), "<")])  # a little-endian log
        lines = hfp_codec.verdict(hfp_codec.read(log))
        self.assertIn("NO, so it can only do CVSD", lines[0])
        self.assertIn("codecs the car offers (AT+BAC): none offered", lines)
        self.assertTrue(lines[-1].startswith("verdict: NARROWBAND"))

    def test_the_accept_command_has_its_coding_after_an_address(self):
        found = hfp_codec.read(record(0, accept(0x05)) + record(1, link(3)))
        self.assertEqual(found["asked"], [0x05])
        self.assertTrue(hfp_codec.verdict(found)[-1].startswith("verdict: WIDEBAND"))

    def test_only_links_that_were_made_count(self):
        log = b"".join([record(0, setup(0x05)), record(1, failed()), record(0, setup(0x02)), record(1, link(2))])
        self.assertTrue(hfp_codec.verdict(hfp_codec.read(log))[-1].startswith("verdict: NARROWBAND"))
        cvsd = hfp_codec.read(record(3, acl(b"+BCS: 1")))  # agreed on CVSD, no link in the log
        self.assertTrue(hfp_codec.verdict(cvsd)[-1].startswith("verdict: NARROWBAND"))

    def test_no_call_and_no_log(self):
        self.assertIn("no call audio", hfp_codec.verdict(hfp_codec.read(record(2, acl(b"AT+BRSF=191"))))[-1])
        with self.assertRaises(ValueError):
            hfp_codec.read(b"not a log")

    def test_prints_no_address(self):
        lines = "\n".join(hfp_codec.verdict(hfp_codec.read(record(1, link(2)))))
        self.assertNotIn("aa:aa", lines.lower())
        self.assertNotIn("aaaaaa", lines.lower())


if __name__ == "__main__":
    unittest.main()

"""Narrowband or wideband? Read an iPhone's Bluetooth log of a call in the car.

Usage: python3 tools/hfp_codec.py LOG.pklg

LOG.pklg is the Bluetooth log (PacketLogger format) from an iPhone's sysdiagnose, made with
Apple's Bluetooth logging profile while a call ran over SYNC (docs/CALL-SOUND.md). The tool
reads only what decides the call sound:

- the car's hands-free features (AT+BRSF): may it negotiate a codec at all (HFP 1.6)?
- the codecs the car offers (AT+BAC: 1 = CVSD, 2 = mSBC) and the one the phone picks (+BCS);
- each audio link as the radio set it up: its air mode (CVSD, or transparent for mSBC) and
  the coding format the phone asked for.

Narrowband (CVSD, 8 kHz) carries the telephone band, about 300-3400 Hz: no bass, "boxy".
Wideband (mSBC, 16 kHz) carries about 50-7000 Hz. It prints no addresses, numbers or names.
"""
import re
import struct
import sys
from pathlib import Path

HCI_COMMAND, HCI_EVENT, ACL_SENT, ACL_RECEIVED = 0x00, 0x01, 0x02, 0x03
SYNC_COMPLETE = 0x2C  # HCI event: Synchronous Connection Complete
# HCI commands: Enhanced Setup / Accept Synchronous Connection -> where the transmit coding format
# sits in the command (opcode 2, length 1, then a handle of 2 or an address of 6, two bandwidths of 4)
ENHANCED = {0x043D: 3 + 2 + 8, 0x043E: 3 + 6 + 8}
AIR_MODES = {0: "u-law", 1: "A-law", 2: "CVSD", 3: "transparent (mSBC)"}
CODING = {0x00: "u-law", 0x01: "A-law", 0x02: "CVSD", 0x03: "transparent", 0x05: "mSBC"}
CODECS = {1: "CVSD", 2: "mSBC"}
HF_CODEC_NEGOTIATION = 1 << 7  # in the hands-free unit's (the car's) AT+BRSF
AG_CODEC_NEGOTIATION = 1 << 9  # in the phone's +BRSF
AT = re.compile(rb"(AT\+BRSF=\d+|\+BRSF: ?\d+|AT\+BAC=[\d,]+|\+BCS: ?\d+|AT\+BCS=\d+)")


def records(data: bytes):
    """(type, payload) for every record. PacketLogger headers are a length and a time stamp,
    big-endian in most logs and little-endian in some, so both are tried."""
    for order in (">", "<"):
        out, p = [], 0
        while p + 12 <= len(data):
            length = struct.unpack_from(order + "I", data, p)[0]
            if length < 9 or p + 4 + length > len(data):
                break
            out.append((data[p + 12], data[p + 13:p + 4 + length]))
            p += 4 + length
        if out and p == len(data):
            return out
    raise ValueError("not a PacketLogger log (or a damaged one)")


def read(data: bytes) -> dict:
    found = {"car_features": [], "phone_features": [], "offered": [], "chosen": [], "links": [], "asked": []}
    for kind, payload in records(data):
        if kind in (ACL_SENT, ACL_RECEIVED):
            for match in AT.findall(payload):
                text = match.decode("ascii")
                number = re.findall(r"\d+", text)
                if text.startswith("AT+BRSF="):
                    found["car_features"].append(int(number[0]))
                elif text.startswith("+BRSF"):
                    found["phone_features"].append(int(number[0]))
                elif text.startswith("AT+BAC="):
                    found["offered"].append([int(n) for n in number])
                else:  # +BCS: the phone's choice, AT+BCS: the car confirming it
                    found["chosen"].append(int(number[0]))
        elif kind == HCI_EVENT and len(payload) >= 19 and payload[0] == SYNC_COMPLETE and payload[2] == 0:
            found["links"].append(payload[18])  # status 0 (made); air mode is the last parameter
        elif kind == HCI_COMMAND and len(payload) >= 3 and struct.unpack_from("<H", payload)[0] in ENHANCED:
            at = ENHANCED[struct.unpack_from("<H", payload)[0]]
            if len(payload) > at:
                found["asked"].append(payload[at])
    return found


def verdict(found: dict) -> list[str]:
    lines = []
    if found["car_features"]:
        features = found["car_features"][-1]
        lines.append(f"car's hands-free features (AT+BRSF): {features} (0x{features:x}); codec negotiation: "
                     + ("yes" if features & HF_CODEC_NEGOTIATION else "NO, so it can only do CVSD"))
    if found["phone_features"]:
        features = found["phone_features"][-1]
        lines.append(f"phone's features (+BRSF): {features}; codec negotiation: "
                     + ("yes" if features & AG_CODEC_NEGOTIATION else "no"))
    lines.append("codecs the car offers (AT+BAC): " + (", ".join(CODECS.get(c, str(c)) for c in found["offered"][-1])
                                                        if found["offered"] else "none offered"))
    if found["chosen"]:
        lines.append("codec chosen (+BCS): " + CODECS.get(found["chosen"][-1], str(found["chosen"][-1])))
    for mode in found["links"]:
        lines.append(f"audio link: air mode {AIR_MODES.get(mode, mode)}")
    for code in found["asked"]:
        lines.append(f"audio link asked for: {CODING.get(code, hex(code))}")
    # what decides it: the links that were made; without any, the codec the two sides agreed on
    if found["links"]:
        wide, narrow = 3 in found["links"], 2 in found["links"]
    else:
        wide, narrow = 2 in found["chosen"][-1:], 1 in found["chosen"][-1:]
    if not (wide or narrow):
        lines.append("verdict: no call audio in this log; make a call while the profile is installed")
    elif wide and not narrow:
        lines.append("verdict: WIDEBAND (mSBC, 16 kHz, about 50-7000 Hz)")
    elif narrow and not wide:
        lines.append("verdict: NARROWBAND (CVSD, 8 kHz: the telephone band, about 300-3400 Hz)")
    else:
        lines.append("verdict: both kinds of link in this log (several calls?); see the lines above")
    return lines


def main(argv: list[str]) -> None:
    if len(argv) != 1:
        raise SystemExit(__doc__)
    for line in verdict(read(Path(argv[0]).read_bytes())):
        print(line)


if __name__ == "__main__":
    main(sys.argv[1:])

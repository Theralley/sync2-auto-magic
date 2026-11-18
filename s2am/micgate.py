"""AutoKit records from the car's microphone only on head units it knows: open that gate.

When the dongle tells AutoKit to use the car's microphone (command 7), AutoKit asks a small
function whether this head unit is one of a few known platforms, and keeps the answer in a
flag. Only with the flag set does the dongle's "start recording" (command 1) open a recording
device. On SYNC 2 the answer is no, so AutoKit never records and CarPlay hears nothing (Siri
started in CarPlay, calls). ``open_gate`` changes the function's "no" (``mov r0, #0``) to "yes"
(``mov r0, #1``): one instruction, found by the shape of the whole function, and refused
unless exactly one place in the program has that shape.
"""
from __future__ import annotations

import struct

# The function, word by word; None is a word that differs between builds (branch targets, a
# literal offset). str lr,[sp,#-4]! / bl platform / cmp r0,#0 / beq yes / cmp r0,#9 / beq yes /
# cmp r0,#5 / beq yes / cmp r0,#1 / beq yes / cmp r0,#10 / beq yes / cmp r0,#6 / bne no /
# ldr r1,=name / mov r0,#0 / bl / bl / cmp r0,#0 / bne yes / no: mov r0,#0 / pop {pc} /
# yes: mov r0,#1 / pop {pc}
SHAPE = (0xE52DE004, None, 0xE3500000, 0x0A000011, 0xE3500009, 0x0A00000F, 0xE3500005, 0x0A00000D,
         0xE3500001, 0x0A00000B, 0xE350000A, 0x0A000009, 0xE3500006, 0x1A000005, None, 0xE3A00000,
         None, None, 0xE3500000, 0x1A000001, 0xE3A00000, 0xE49DF004, 0xE3A00001, 0xE49DF004)
ANSWER = 20           # the word that says no
NO, YES = 0xE3A00000, 0xE3A00001
OPENED = SHAPE[:ANSWER] + (YES,) + SHAPE[ANSWER + 1:]


class GateError(Exception):
    pass


def _find(module: bytes, shape) -> list[int]:
    words = struct.unpack_from(f"<{len(module) // 4}I", module)
    return [4 * i for i in range(len(words) - len(shape) + 1)
            if all(want is None or words[i + k] == want for k, want in enumerate(shape))]


def is_open(module: bytes) -> bool:
    """Has this AutoKit.exe the gate open already? Raises if it has neither form exactly once."""
    closed, opened = _find(module, SHAPE), _find(module, OPENED)
    if len(closed) + len(opened) != 1:
        raise GateError(f"the microphone gate was found {len(closed) + len(opened)} times, not once")
    return bool(opened)


def open_gate(module: bytes) -> bytes:
    """``module`` with the gate open; the same bytes back if it is open already."""
    if is_open(module):
        return module
    offset = _find(module, SHAPE)[0] + 4 * ANSWER
    return module[:offset] + struct.pack("<I", YES) + module[offset + 4:]

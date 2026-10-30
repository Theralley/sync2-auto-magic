"""Read job scripts the way the car's MortScript does, and avoid its line-split bug.

The MortScript.exe that SyncExtPack ships (4.3.0.15) pre-parses a whole script
before running any of it; an unbalanced block stops the script with a dialog.
Its rules, taken from the binary:

- a comment starts at '#', ';' or '//' anywhere outside a "..." or '...' string;
- a line ending in a backslash continues on the next line;
- a line whose first word is followed by '=', '%', '[' or 'op=' is an assignment.

Its command splitter has a bug: on a line that is a bare word (``EndIf``,
``EndForEach``, ``Exit``, ...) it reads the character just before the line's
buffer, and when that stray character happens to be a space or tab it returns
an empty command. The keyword is then lost: a lost ``EndIf`` leaves its ``If``
unclosed ("'If' without 'EndIf'"), and a lost ``Exit`` at run time lets a script
carry on past its guard. Writing the word with empty brackets (``EndIf()``)
gives the splitter a separator, so it never looks before the buffer, and the
interpreter ignores the empty parameters.
"""
from __future__ import annotations

import re

WORD = re.compile(r"[A-Za-z0-9_@]+")
OPENERS = {"IF", "FOR", "FOREACH", "WHILE", "REPEAT", "SWITCH", "CHOICE", "CHOICEDEFAULT",
           "TRY", "SUB"}
CLOSERS = {"ENDIF": ("IF",), "NEXT": ("FOR",), "ENDFOR": ("FOR",), "ENDFOREACH": ("FOREACH",),
           "ENDWHILE": ("WHILE",), "ENDREPEAT": ("REPEAT",), "ENDTRY": ("TRY",),
           "ENDSUB": ("SUB",), "ENDSWITCH": ("SWITCH", "CHOICE"),
           "ENDCHOICE": ("CHOICE", "CHOICEDEFAULT")}
MIDDLES = {"ELSE": ("IF",), "ELSEIF": ("IF",), "CATCH": ("TRY",),
           "CASE": ("SWITCH", "CHOICE", "CHOICEDEFAULT"),
           "DEFAULT": ("SWITCH", "CHOICE", "CHOICEDEFAULT")}


class ScriptError(ValueError):
    pass


def harden(line: str) -> str:
    """Write a bare-word line as ``Word()`` so the car's splitter cannot drop it."""
    word = line.strip()
    if WORD.fullmatch(word):
        return line.rstrip() + "()"
    return line


def strip_comment(line: str) -> str:
    line = line.strip()
    single = double = False
    for i, char in enumerate(line):
        if char == "'" and not double:
            single = not single
        elif char == '"' and not single:
            double = not double
        elif not (single or double) and (char in "#;" or line.startswith("//", i)):
            return line[:i].rstrip()
    return line


def logical_lines(text: str):
    """(first line number, logical line) as the car reads them."""
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        number, line = i + 1, strip_comment(lines[i])
        while line.endswith("\\") and i + 1 < len(lines):
            i += 1
            line = line[:-1].rstrip() + " " + strip_comment(lines[i])
        i += 1
        if line:
            yield number, line


def _command(line: str) -> tuple[str, bool]:
    """(command word, is it an assignment) for one logical line."""
    match = WORD.match(line)
    end = match.end() if match else 0
    rest = line[end:].lstrip(" \t")
    assignment = bool(rest) and (rest[0] in "%[=" or (len(rest) > 1 and rest[1] == "="
                                                       and rest[0] in "+-*/&|.^"))
    return line[:end], assignment


def check(text: str) -> None:
    """Raise ScriptError for anything the car's MortScript would stop on or misread."""
    stack: list[tuple[str, int]] = []
    for number, line in logical_lines(text):
        word, assignment = _command(line)
        if assignment:
            continue
        if WORD.fullmatch(line):
            raise ScriptError(f"line {number}: bare {line!r} can be dropped by the car's "
                              f"MortScript; write {line}()")
        cmd = word.upper()
        if cmd in OPENERS:
            stack.append((cmd, number))
        elif cmd in CLOSERS or cmd in MIDDLES:
            wanted = CLOSERS.get(cmd) or MIDDLES[cmd]
            if not stack or stack[-1][0] not in wanted:
                found = f"open {stack[-1][0]} from line {stack[-1][1]}" if stack else "nothing open"
                raise ScriptError(f"line {number}: {word} with {found}")
            if cmd in CLOSERS:
                stack.pop()
    if stack:
        kind, number = stack[-1]
        raise ScriptError(f"line {number}: {kind} is never closed")

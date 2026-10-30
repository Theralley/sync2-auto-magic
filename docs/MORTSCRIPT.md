# MortScript on SYNC 2: the rules s2am follows

Every `s2am` job runs a MortScript on the car, using the `MortScript.exe` that SyncExtPack ships
(version 4.3.0.15). These notes come from the first car session (30 October 2026) and from
disassembling that exact binary. `s2am/mortscript.py` applies them, and every job script is
checked before a stick is built.

## It reads the whole script before running it

MortScript pre-parses the whole file to find where each block starts and ends. If a block is
unbalanced it shows a dialog such as **"'If' without 'EndIf'"** and runs nothing at all. The
SyncExtPack installer still reports *"Install successfully completed!"* after you tap OK,
because it ignores the script's result. So a stick with a script error comes back with no
report.

## Bare keyword lines can be dropped

The first inventory stick failed in the car with "'If' without 'EndIf'" on line 46, although
the script was balanced.

The cause is a bug in MortScript's line splitter (at `0x17d90` in the unpacked binary). On a
line that is a single word, such as `EndIf`, `EndForEach`, `Else`, `EndWhile` or `Exit`, it
reads the character just **before** the line's memory buffer. When that stray character
happens to be a space or a tab, it returns an empty command, and the keyword is lost.

- A lost `EndIf` leaves its `If` open, which is what happened on line 46.
- A lost `Exit` would let a script run on past its guard.
- Whether it happens depends on what is in memory. In that script only one `EndIf` out of five
  was hit.

**The fix:** `s2am` writes every bare keyword with empty brackets, as `EndIf()`, `Exit()`,
`EndForEach()` and so on. The bracket gives the splitter a separator, so it never looks before
the buffer. The interpreter ignores the empty parameters. Since this fix, every job script has
run cleanly in the car.

If you write MortScript for SYNC 2 by hand, do the same.

## Comments start at `#`, `;` or `//` anywhere

A comment starts at `#`, `;` or `//` anywhere on a line, unless it is inside a string. Strings
can use `"..."` and also `'...'`. A line that ends in a backslash continues on the next line.
A line whose first word is followed by `=`, `+=`, `%` or `[` is an assignment.

## How s2am guards this

- `mortscript.harden()` rewrites bare keyword lines. `job._script()` applies it to every
  script it builds.
- `mortscript.check()` models the car's pre-parse: comments, continuations, assignments, and
  block matching for If, ForEach, While, For, Repeat, Switch, Choice, Try and Sub. It also
  refuses any bare keyword. A script that fails the check is never put on a stick.
- `tests/test_mortscript.py` includes the exact script that failed in the car.

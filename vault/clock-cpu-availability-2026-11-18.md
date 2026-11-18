# CPU-counter availability diagnostic
A read-only permission/control probe is built and host-tested, but has not been run in the car or placed on USB.

The next concrete component after the transition coordinator is now implemented:
`s2amcpuprobe.c` reads USEREN first, stops when disabled, otherwise reads only PMNC/CNTENS.
There is no CCNT sampling, MCR, enable/reset, QPC, mapping, driver or kernel fallback.
Control bits identify only an existing configuration, never measured CPU frequency.

The exact four/eight-record CRLF report is bounded. Progress must flush before each read;
independent clean child exit is indispensable even if a terminal record is visible. Faults,
timeouts, malformed/partial reports and failed final I/O remain inconclusive, not denial.
Host interpretation always denies rate qualification, write authority and retry permission.

16 CPU-specific tests pass, including ASan/UBSan C execution, all 29 write-failure positions
and 12 actual-C-byte/actual-exit parser round trips. Combined focused checks total 72 tests.
One isolated local experimental CE build produces a 6,144-byte ARM/CE executable with only
three allowed CP15 reads and COREDLL imports. No full CI or production build ran.

Executable SHA-256: `abdc9ea572b9d20ad784902b64acf00b3312cb59c56619ad9a41bf240a5e5c27`.
The matching source snapshot is bound in local build receipts. Import availability in a
candidate firmware is not live firmware identity or proof of on-car execution.

**No USB package exists.** A separately reviewed fault-containing parent and one-shot
identity-bound collection are still needed. Host fault simulation does not prove real CE
exception containment. No existing claim was removed and no consumed job was replayed.

See [full scope and artifact](../docs/CLOCK-CPU-AVAILABILITY-2026-11-18.md),
[[clock-transition-2026-11-18]] and [[clock-qualification-return-2026-11-18]].

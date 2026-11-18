# CPU-counter availability diagnostic
A new gated, three-layer read-only diagnostic is prepared, remount-verified and safely ejected on NO NAME; car execution remains unverified.

## Current USB preparation

Job `20261118-164459-cpuavail-3226` is now prepared on the identified NO NAME stick.
Pack: 40,352 bytes, SHA-256
`af76bd0fe09fbd4b407969628750ccf0cbe568721ff0238cf86ef1691aac8769`.
Backup/hash verification preceded the write; pack/pending/instructions matched after ordinary
unmount/remount and the stick was safely ejected. Other sticks were untouched.

Three executables plus job.json only: outer collector independently checks debug-controller
exit; controller requires attachment before signalling a fresh named event; child requires
that pre-existing signalled event before any MRC. Every exception is inconclusive, no PC
adjustment or ordinary-launch fallback exists. Existing clock claims remain untouched and
new CPU one-shot state remains retained. No frequency/voltage/PMU setting is changed.

140 focused tests pass, including real-C multi-layer producer/consumer tests and sanitized
fault paths. Three independent source reviewers and a separate final artifact review clear
read-only diagnostic preparation, not on-car permissions or overclock safety. The earlier
ungated 6,144-byte artifact below is historical and must not be deployed.

Insert once while parked, wait for installation completion plus one minute, then return it
for evidence preservation and import. At an error, take a photograph and do not repeat.
Package window ends December 17, 2026, 09:35:59 UTC. A successful installation screen does
not establish usable CPU observations. No car return for this job exists yet.

## Earlier standalone stage (historical)

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

**At this earlier stage no USB package existed.** A separately reviewed fault-containing parent and one-shot
identity-bound collection are still needed. Host fault simulation does not prove real CE
exception containment. No existing claim was removed and no consumed job was replayed.

See [full scope and artifact](../docs/CLOCK-CPU-AVAILABILITY-2026-11-18.md),
[[clock-transition-2026-11-18]] and [[clock-qualification-return-2026-11-18]].

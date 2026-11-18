# CPU-counter availability diagnostic
Controlled v2 CPU diagnostic is prepared, remount-verified and ejected; first return was inconclusive, no overclock is qualified.

## New controlled successor USB ready, November 18

NO NAME now contains **`20261118-174115-cpuavail-dbf6`**, a new read-only v2 diagnostic.
Its **48,760-byte** pack has SHA-256
`34b579e33ac385ec36c073e15e29be44c18699c1e0728a6ea47c70c9924e1f4c`.
The official unpacker reproduced all five staged files exactly: three executables, the
predecessor receipt and `job.json`. No MortScript, restart or clock writer is included.

All 57 earlier managed USB files were backed up and hash-verified before mutation. Consumed
updater files and old root instructions were archived, not replayed. New pack, single pending
identity and Swedish instructions matched after ordinary unmount/remount; NO NAME was then
**safely ejected**. Other sticks were untouched. Valid before **December 17, 2026, 09:35:59 UTC**.

The source/test commit `84079ac` remains local. **116 focused checks** pass; three source
reviews and a separate compiled-artifact review clear this bounded read-only diagnostic.
The raw PE files matched all **7,027 disassembly words**. All 28/40/40 direct imports resolve
in the inspected candidate COREDLL; six ordinary Toolhelp exports and the actual candidate
structure sizes were checked. Candidate availability is not live firmware identity or
permission proof. No full CI, server run or production build was performed.

Insert **once while parked**, wait for the install completion message plus at least one
minute, then return the stick for preservation and import. Photograph an error and do not
repeat. Root instructions: `S2AM-CPU-SUCCESSOR-20261118.txt`. This completes USB preparation,
**not** on-car CPU observation, measured frequency or overclock qualification.


## Actual returned CPU diagnostic, November 18

The first CPU job `20261118-164459-cpuavail-3226` returned and was preserved before import.
Its 243-byte controller journal stopped at `E|api|debug-wait|258`, before positive debugger
attachment or gate release; the probe report is absent. The outer collector independently
observed controller exit 1. Import is **not verified**, not a CPU permission denial. No CPU
values, rate measurement, PMU enablement or clock change resulted.

The bound controller rejected CE's actual 258 poll-timeout form. A focused regression now
accepts that form while retaining the event/deadline bounds. Original reports, installed pack
and all one-shot state remain preserved; the consumed job must not be replayed.

The controlled v2 successor above retains the original claim, pins the exact predecessor
evidence, requires two fresh process checks and consumes one fixed predecessor edge. Its
probe starts behind a closed event and may read only after positive debugger attachment.
It never enables PMU or changes clocks. Its actual car return remains the next step.


## Historical first USB preparation

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
not establish usable CPU observations. This first job has now returned; see the actual-return section above.

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

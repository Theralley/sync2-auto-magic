# Single-port start/collect lifecycle
The observer wire format is unchanged. S2AMCTL.EXE is a manual, one-run controller.

## Fixed scope

The controller accepts no arguments. Its executable must be in S2AM-LOAD on a known
USB mount (USB Disk, USB Disk1, USB Disk2, USB Disk 2 or USB Disk3). The only payload
is S2AMLOAD.EXE next to it. Its expected byte size and SHA-256 are compiler defines,
bound to the separately built, reviewed collector in the same artifact manifest.

Car run directory is fixed:
`\SyncExtendedPack\_s2am\load\20261120-load-44748284729`.
Only its own parent/run folders and files may be created. No old claims, jobs, apps,
registry, clock, power or priority settings are touched. No process is terminated.

## First manual launch: start

Create parent directories if missing and reserve the new run directory exclusively.
Write START.CLAIM with exactly `S2AM-LOAD-START,1\r\n<expected SHA-256>\r\n`, flush/close.
Copy the hash-pinned collector into the run directory with CREATE_NEW and checked
writes/flush/close; reread and hash-check the copied executable. Failure leaves the
claim/run directory, never removes it and never starts another collector on retry.

CreateProcessW targets only that fixed internal executable, with no arguments. Observe
up to 20 x 250 ms readiness polls: process must be WAIT_TIMEOUT (still running), and
its observed LOAD.TMP prefix must contain the expected header, fixed meta constants,
child PID/TID and a positive frequency line. No claimed synchronous completion.
This observation is not journal crash-durability or completion proof.
Any error/early exit/deadline is uncertain; never kill/relaunch. On confirmed readiness,
write a new STARTED.TXT USB receipt. Close child handles before displaying the result.
The user closes the controller dialog/application before removing the USB and inserting
CarPlay. The child runs internally, independently of the removed stick.

## Later manual launch: collect, never restart

If the fixed run directory already exists, require matching START.CLAIM and hash-pinned
internal collector; never create another process. If LOAD.CSV does not yet exist, report
not ready/failed and do not change the run. Existing empty/foreign/partial directories
are refusal, not permission to take over or delete them.

Collection accepts only fixed internal LOAD.CSV, 1..8 MiB, header S2AM-LOAD,1 CRLF and
footer complete,60 CRLF. Check a bounded stream and SHA-256; rewind the held read-only
source descriptor. Destination on the USB is LOAD.TMP CREATE_NEW; copy the source with
checked writes/flush/close, verify destination SHA-256, then non-replacing MoveFile to
LOAD.CSV. Existing USB LOAD.CSV or LOAD.TMP refuses collection without overwriting.
A partial copy remains scratch. No internal file is deleted; subsequent collection is
read-only with respect to the car. The desktop strict parser remains authoritative;
header/footer/hash checks alone do not qualify CPU observations.

## Failure/budget boundaries

Each synchronous read/copy is bounded by expected size or 8 MiB; zero-progress/error/oversized-count I/O and failed close/flush prevent success.
Positive short streaming transfers are accumulated; fixed-length claim and readiness
reads must meet their own exact-content acceptance checks. Reads preserve immediate errors where needed.
Admission budget is 30 s by DWORD GetTickCount subtraction, including wrap. API calls
cannot be hard-cancelled. Readiness failure never clears a claim or terminates a child.
No arbitrary address/path/process interface or privilege fallback is introduced.

Targeted host tests must exercise first start, later collect without another start,
wrong payload/claim, existing outputs, partial failures, delayed readiness, child exit/
wait error, budget expiry, internal-copy/readback failures, and non-replacing publish.
CE ARM build, imported APIs, binary identity and disassembly require independent review
before USB deployment. A start receipt is not a completed recording.

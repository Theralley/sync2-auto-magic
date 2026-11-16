# Temporary user-mode clock reader

A server-built, one-shot CE 6 diagnostic attempts the fixed PLL1/CCM snapshot from an
isolated Device Manager user-driver host. It has not been activated in the car.

The ordinary `s2amclock.exe` application failed its first `MmMapIoSpace` call with error 87
in the car and produced no register reads. Analysis of the candidate user CEDDK/COREDLL/
Device Manager route indicates that the caller must be a registered user-driver host.
This diagnostic tests that supported host route. It does not change frequency, voltage,
interrupts, boot configuration, or any MMIO register. It has not been activated in the car.
The inferred mapping explanation and firmware identity still need runtime confirmation.

## Files and activation boundary

`s2amclkdrv.c` plus `s2amclkdrv.def` build the `SCK` stream DLL. `s2amclockctl.c` builds
a controller bound to that exact DLL's SHA-256 and byte length. `clock_probe_protocol.h`
defines the pointer-free snapshot and shared registry contract. `s2amclockjob.c` is the
native `POST_APP` launcher for the separate `clock-inspect` job. The job accepts only a
source-bound bundle already compiled on `ant-srv-001`; artifact loading never builds locally.
It stages exactly the three binaries and `job.json` in its own job directory. No interpreter,
decoder, active application replacement, or restart directive is included.

The controller accepts one run ID of 1–40 lowercase ASCII letters, digits, or hyphens.
Its executable must be at the exact derived path:

```
\SyncExtendedPack\_s2am\jobs\<run-id>\s2amclockctl.exe
\SyncExtendedPack\_s2am\jobs\<run-id>\s2amclkdrv.dll
\SyncExtendedPack\_s2am\jobs\<run-id>\clock-user-driver.txt
```

The report uses `CREATE_NEW`, so an existing report prevents a rerun. The DLL is opened for
read with only `FILE_SHARE_READ`, hashed completely, and checked for exact size including EOF.
That handle remains open until cleanup; it denies new write/delete opens while permitting
loader reads. The compiled digest binds reviewed artifacts; it is not a signature, and it does
not authenticate the recovered firmware. The local job directory and registry are assumed to
be under trusted control; this is not protection against another privileged CE process.

The controller creates the exclusive, device-wide `HKLM\Drivers\S2AMClock` key and requires
`REG_CREATED_NEW_KEY`. It never overwrites an existing key, including one from a different
run. The key is outside `BuiltIn`.
Exactly these seven values, with exact types and bytes, must read back correctly:

| Value | Type | Data |
| --- | --- | --- |
| `Dll` | `REG_SZ` | Absolute derived DLL path above |
| `Prefix` | `REG_SZ` | `SCK` |
| `Flags` | `REG_DWORD` | `0x10` (`DEVFLAGS_LOAD_AS_USERPROC`) only |
| `InterfaceType` | `REG_DWORD` | `0` (`Internal`) |
| `BusNumber` | `REG_DWORD` | `0` |
| `MemBase` | `REG_MULTI_SZ` | `83f80000`, `73fd4000` |
| `MemLen` | `REG_MULTI_SZ` | `30`, `58` |

The hexadecimal multi-strings include the final double NUL. Extra values or subkeys fail
validation. `Index`, `UserProcGroup`, `IoBase`, `IoLen`, interrupt fields, and `Context` are
absent. The controller first reads `HKLM\Drivers` and requires exact `REG_SZ` values
`ProcName=udevice.exe` and `ProcVolPrefix=$udevice`, including their terminating NULs;
omitting `UserProcGroup` requests a separate host instead of joining Ford's groups 2 or 3.
The returned November 15 registry capture contains those defaults, and every activation
attempt checks them again. This configuration check does not prove that CE starts the host.

After `ActivateDeviceEx`, both NULL and `INVALID_HANDLE_VALUE` are failure/ambiguous results.
The controller obtains device information by the returned activation handle and requires the
same handle and exact original key path. Only a returned, terminated `SCK[0-9]:` name is opened,
with `GENERIC_READ` and no sharing. Information obtained again from the stream file handle must
identify the same activation, registry key and legacy name before any snapshot request.

## DLL behavior and fixed wire contract

`SCK_Init` uses `OpenDeviceKey(active_key)` to validate the original key, including its own
actual DLL path. Init and Open do not load CEDDK, map memory, or read hardware. Each isolated DLL
instance allows one read-only stream open for its lifetime; closed contexts are never recycled.
Read, Write, and Seek return `ERROR_NOT_SUPPORTED`.

`SCK_IOControl` accepts only `0x00226004`: `FILE_DEVICE_UNKNOWN`, function `0x801`,
`METHOD_BUFFERED`, `FILE_READ_ACCESS`. Input pointer and size must both be zero; output must be
exactly 1,056 bytes with a returned-byte-count pointer. Unknown operations, malformed sizes and
invalid contexts are rejected before loading or mapping. Calls serialize with an atomic busy
flag; concurrent calls fail with `ERROR_BUSY` instead of queuing behind a stalled access.

The record contains eight 32-bit header words followed by 64 four-word readings:

```
magic = 0x314b4353; version = 1; bytes = 1056
status = 0 complete / 1 failed; stage; error; count; reserved = 0
reads[64] = { pass, block, offset, value }
```

It has no pointers or caller-controlled physical addresses. A valid IOCTL returns transport
success even when sampling failed; `status`, `stage`, `error`, and `count` describe that failure.
Error zero is possible from a failed CE API and still means failure when status is failed.

| Stage | Meaning |
| --- | --- |
| 1 / 2 | Load installed `\Windows\ceddk.dll` / resolve three ordinary exports |
| 3 / 4 | Translate / map PLL1 at `0x83f80000`, length `0x30` |
| 5 / 6 | Translate / map CCM at `0x73fd4000`, length `0x58` |
| 7 | Fixed register reads |
| 8 | Failed library cleanup |
| 9 | Complete reads and mapping/library cleanup |

`HalTranslateBusAddress(Internal, 0, ...)` must return memory space and exactly the fixed
expected physical address. The driver then calls ordinary `MmMapIoSpace` with caching disabled.
It never loads a `k.*` library or calls a kernel fallback. Mappings may be writable at the API
level, but the implementation uses only volatile const DWORD loads.

Passes 1 and 2 each read CCM-before (block 1), PLL1 (block 2), then CCM-after (block 3):

```
CCM offsets:  0, 8, 12, 16, 20, 24, 28, 32, 72, 76, 84
PLL1 offsets: 0, 4, 8, 12, 16, 28, 32, 36, 40, 44
```

The snapshot owner alone unmaps, in reverse order, including after partial mapping failure.
PreClose and PreDeinit atomically invalidate their contexts; checks between reads stop further
sampling once invalidation is observed. They neither free mappings nor wait for an in-flight
operation. Deinit/Close reject an unexpectedly busy context. Device Manager's documented
PreClose/PreDeinit lifetime sequencing is still required before it unloads the DLL.

## Journal, completion, and pending outcomes

Before launching the controller, the native job creates, flushes and closes both its own
`clock-job-entry.txt` and the device-wide
`\SyncExtendedPack\_s2am\clock-inspection-claim.txt`, each using `CREATE_NEW`. The latter
remains on **every outcome, including success**. A new job ID therefore cannot bypass a
timed-out child that has not yet reached registry creation. No release/delete operation is
provided; another attempt requires separately reviewed reconciliation of the prior run.

The launcher requires exactly one known USB mount with the matching pending job, then a
new report directory. It waits 15 seconds for the controller and records the actual wait
result, validity of the exit code and exit code. It never kills or retries the child. It copies
at most 32 KiB of the observed journal prefix and binds it with byte count and CRC32 in
`clock-job.txt`. A 60-second cooperative I/O budget stops further calls; it cannot cancel an
already blocked CE call. `done.txt` means that collection completed, not that activation,
register sampling or cleanup succeeded. A timeout stays unresolved even if the copied
journal later contains a success-looking marker.

The controller flushes a progress record before activation, identity lookup, stream open,
snapshot IOCTL, stream close, deactivation and registry deletion. A failure to write or flush
stops later lifecycle calls. The report retains the existing `S|s2am-clock-v1`, `R|...`, and
`T|complete` format; new `B|...` records remain informational. The controller validates the
entire fixed recordset before emitting any register records. It makes no frequency claim.

Successful cleanup closes the stream, passes the **activation handle to `DeactivateDevice`**,
then deletes only the key it exclusively created. `CloseHandle` is never used on the activation
handle. A failed stream close or deactivation preserves the registry key. Pre-activation failures
and either activation failure sentinel also retain the key as evidence. No path deletes the DLL.
Only a valid snapshot plus confirmed cleanup produces `T|complete`; final flush/close failure
still produces a nonzero process exit, even if marker bytes are present. The existing parser's
successful-child check remains mandatory.

An activation, MMIO load, unmap, or deactivation can block. The flushed journal locates the
last entered controller phase; it cannot locate an individual in-driver load or prove that an
interrupted phase did not happen. A parent's timeout does not cancel the child or physical load.
On an ambiguous/pending outcome, preserve the report, DLL, key and process state. Do not retry,
kill the host, delete the key/DLL, or claim rollback. Reconcile actual active-device state under
a separately reviewed recovery procedure first. The process exiting is not evidence that the
driver was deactivated.

## Verification and build provenance

Focused host tests compile the real C against Windows API fakes. Fake MMIO pages are read-only,
so a register store faults. Cases cover exact 64-read order, strict registry values and types,
invalid IOCTLs, partial mappings, translation mismatch, concurrent calls, close/deinit
invalidation, DLL byte/size/read failures, activation sentinels, two identity checks, malformed
snapshot records, journal errors, cleanup errors, and compatibility with the existing parser.
SHA-256 matches standard empty/`abc`/long vectors, one million `a` bytes, and padding/block
boundaries. These are logic tests; they do not emulate CE process isolation or prove mapping
permission, clock stability, runtime ABI behavior, or vehicle safety.

The independent November 16 review found a test-oracle gap: the fake registry originally
used the production value table as its expected data. Changing `Flags` from `0x10` to `0`
therefore passed the original tests, even though that would request kernel-mode loading.
The fixture now specifies all seven names, types and values independently. Additional cases
cover malformed memory lengths/double NULs, bus mismatch, registry/DLL close failures,
different valid stream names and journal-flush failure before each cleanup operation.
A mutation check on November 16 then showed that several stated checks could be removed
without a failing test. The suite now also runs the real driver behind the real controller
(snapshot, failed-sampling records and Init refusal), and covers invalidation between reads,
busy Close/Deinit, the registry `Dll` path, every snapshot header field, the run-ID rules
separately from the executable-path binding, a failed stream open and a crash inside activation.
A follow-up review added a status-only bad snapshot, each missing CEDDK export on its own, and
invalidation immediately after Open or IOControl acquires its flag.
The current 29 driver/controller tests and five parser tests pass. Thirteen additional
launcher/import tests exercise the actual C producer, bounded copy failures, child exit and
timeout handling, same-run and cross-run replay barriers, exact native-only staging, trusted
job identity and source/artifact binding. The CLI stages this job even without `--no-pack`;
it cannot accidentally invoke the local packer. The new controller additionally tests
runtime host-configuration refusal.

Run the focused checks with:

```sh
python3 -m unittest discover -s tests -p test_clock_driver.py
python3 -m unittest discover -s tests -p test_clock_job.py
python3 -m unittest discover -s tests -p test_clock_transition_model.py
```

The November 16 build ran only on `ant-srv-001`, using the existing digest-pinned image
`ghcr.io/enlyze/windows-ce-build-environment-arm@sha256:22ea23d697accaab2b98fb12d81ccc1faade90f9fe490f554ae7c5c194dfe27c`.
It uses `-O2 -Wall -Wextra -Werror`, builds and strips the DLL first, then supplies its SHA-256
as the quoted `SCK_EXPECTED_DLL_SHA256` and its decimal byte length as `SCK_EXPECTED_DLL_SIZE`
when compiling the controller. All three sources explicitly request CE 6 headers. Omitting either
artifact binding prevents controller compilation.

`tools/build_clock_driver.py` refuses hosts other than Linux `ant-srv-001`. Each build uses
an exclusively created output directory, a source-hash manifest and a durable dispatch receipt
before the compiler runs. Latest completed build `6c906abbba5f4481b7eacf26ca3200ff` includes
the device-wide claim and runtime host checks. Local ignored artifacts, `manifest.json` and
`verification.json` reside under
`build/clock-diagnostic-6c906abbba5f4481b7eacf26ca3200ff/artifacts/` in the isolated worktree.
No full CI or Mac native/production build was run.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `s2amclkdrv.dll` | 9,728 | `8ab35d02a623a46bbba3ec5d29e671305ddb2bbaa2d35ee9dcd2bc28b54a86ef` |
| `s2amclockctl.exe` | 12,800 | `369220897aa9edfecaa906d67ce4b0df4d930ca04f5eb6cc5ed27790f4df1afd` |
| `s2amclockjob.exe` | 9,728 | `de692f683d8e2785590aed617de74634e900453dd19d56a5f95a1ea678a5321b` |

All binaries are ARM PE/Windows CE subsystem 9 with COREDLL as their only static import
library. All 29 DLL, 43 controller and 34 launcher imports exist by name in the recovered candidate
COREDLL. The DLL exports exactly the ten declared `SCK_*` entries. Candidate user CEDDK
has `HalTranslateBusAddress` at RVA `0x19d0`, `MmMapIoSpace` at `0x3d60`, and
`MmUnmapIoSpace` at `0x3e28`. The controller binary contains the exact built DLL digest.
These static checks establish candidate symbol availability, not actual-car binary identity.

Stage a source-matching server bundle with:

```sh
python3 -m s2am job clock-inspect --serial <DEVICE_SERIAL> --artifacts <SERVER_BUNDLE_DIR>
```

This command always stops after staging. Packaging and unpack verification also run on
`ant-srv-001`. The first prepared job, `20261116-200227-clkdiag-253b`, contains four payload
files; the server's unpacked files match them byte-for-byte. Its 34,920-byte `install.bin`
has SHA-256 `7fff203769847f9379a4bc252bcae1ab089604039b3d42873ca1067f26a08306`.
Its key window ends **2026-11-17 09:35:59 UTC**; it must not be installed after that time.
The near-boundary package was prepared for local verification and handoff; preparing it
does not record USB preparation or a car result. No USB was modified during this work.

## Plan toward a controlled clock trial

The next deliverable is a successful live clock-tree observation. The application-level
mapping attempt failed before any register read, and this driver has not run in the car.
The following sequence makes each later step depend on a concrete result from the earlier one.

| Step | Work and required result | Current state |
| --- | --- | --- |
| 1. Review the observer | Independently review the DLL/controller, exercise the owned-registry and lifecycle failures, and match the reviewed source to the server artifacts. | Source review and focused checks complete; server-built source/artifact identity checked; no activation performed. |
| 2. Prepare one diagnostic | Add a separately reviewed, one-shot job and import contract that preserves the journal and native exit status. Confirm the target's user-driver host configuration and required runtime identities. A timeout must retain an unresolved outcome and prevent replay. | Native job, importer, persistent cross-run barrier and runtime host checks implemented and independently reviewed. Server package passed unpack comparison. Not run in the car. |
| 3. Establish the baseline | Obtain the 64-read snapshot with successful cleanup. Check both passes, CCM handshakes, active PLL parameter bank/reference configuration, ARM source/divider and DDR selection. Identify the remaining PLL1 consumers and transition state through exact-image analysis and any further reviewed read-only capture needed. Corroborate frequency with an independent timebase. | Live clock-tree registers are missing. The current subset does not enumerate every consumer; an AXI_A DDR selection alone does not establish that every dependent root is independent of PLL1. |
| 4. Specify the transition | Trace a deployed CPU transition implementation or define the necessary platform adapter. Bind its exact preconditions, serialization with Ford policy, register ordering, bounded polls, readback and complete restoration to the observed baseline. Review suspend/resume and applicable silicon errata. | An inert MFN-only transition/restore model and 16 synthetic tests exist. The Ford candidate remains blocked on 19 evidence requirements, with zero operations; no hardware backend or transition implementation exists. |
| 5. Qualify a bounded experiment | Identify the fitted CPU/revision, effective rail and loaded voltage, thermal instrumentation, and a recovery method that still works after loss of CPU/DDR service. Exercise baseline-to-baseline transition and fault recovery on a recoverable bench. | Grade, active voltage, thermal observation and independent recovery remain unresolved. |
| 6. Compare one temporary point | Only after those results, build the matching trial/undo artifacts and perform the reviewed baseline–target–baseline experiment with identical workload. Compare completed work, latency, errors and restoration; preserve any pending result. | No trial artifact exists. The observer adds no frequency/voltage write API. |

### A concrete arithmetic candidate, subject to the live baseline

The recovered candidate NK boot code at `0x801011e0–0x801011f4` writes PLL1
`DP_OP=0x60`, `DP_MFN=1` and `DP_MFD=3`. With the assumed 24 MHz oscillator and
the configuration used by [NXP AN4140 section 3.1](https://www.nxp.com/docs/en/application-note/AN4140.pdf#page=3),
those constants calculate to `4 × 24 × (6 + 1/4) = 600 MHz`. Keeping the same factors
except an MFN of 2 calculates to **624 MHz**, a 4% nominal PLL clock increase and a maximum
3.85% reduction in time for perfectly CPU-scaled work. This narrows the earlier 620–630 MHz
investigation range to a representable arithmetic candidate.

It is not a proposed register-write recipe. Boot constants do not establish the active
normal/high-frequency bank, reference path, dither/auto-restart state, locking behavior or
other live consumers. Those must come from the snapshot, the exact transition code and
any additional reviewed read-only evidence needed beyond the current 64-read subset.
An application-visible mapping also does not provide exclusive ownership of the clock tree.
The current native interface must remain a reader; any future writer needs its own reviewed
contract and implementation.

[NXP errata Rev. 5](https://www.nxp.com/docs/en/errata/IMX51CE.pdf) adds two concrete checks:
ENGcm11208 (p.46) requires separate ARM-source and step-mux changes; ENGcm12051 (pp.155–156)
describes a PLL restart workaround specifically for named consumer variants at 800 MHz.
Neither its temporary 864 MHz value nor the reference BSP's 800 MHz point is a substitute
for a small step on this unidentified fitted part. Actual applicability and restore/resume
behavior must be established before implementing the transition.

The [trial/restoration contract](CLOCK-OUTCOMES.md) continues to apply. Passing the observer's
tests establishes its control logic and artifact identity, not overclock readiness.

### Offline transition and restoration specification

`tools/clock_transition_model.py` emits a blocked candidate specification and five explicitly
synthetic traces. It has no device access, backend or install job. Its 16 tests cover individual
missing prerequisites, stale/partial readbacks, pending apply versus undo, timeout and late
completion, duplicate completions, controller loss, and full-baseline restoration mismatches.
Generate fresh artifacts with:

```sh
python3 tools/clock_transition_model.py --out build/clock-transition-rehearsal
```

[NXP MCIMX51RM Rev. 1](https://www.nxp.com/docs/en/reference-manual/MCIMX51RM.pdf),
section 22.3.3.2, documents MFN-only updates without a PLL restart under its required operating
conditions. Table 22-3 says writing zero to `LDREQ` cannot cancel a pending request, and
Table 22-2 defines `LRF` as sticky. The model therefore requires known settlement plus a
fresh full readback and independent frequency measurement; a previously set lock flag is
insufficient. A pending or timed-out request retains ownership and forbids overlapping undo.
Restoration changes only the owned MFN, completes its own load handshake and checks the
whole baseline. It never replays a raw register dump: section 22.3.3.1 explains that writes to
other PLL configuration fields can restart it even when the values are unchanged.

The 100 ms operation bound and 20 ms observation age are synthetic test fixtures, not
qualified timings for Ford hardware. Likewise the modeled 600/624 MHz observations are
synthetic. Live reference configuration, active bank, clock consumers, Ford policy ownership,
suspend exclusion, loaded voltage, thermal limits and independent recovery remain unknown.

The [NXP CE BSP reference manual, section 9.4.3.2](https://community.nxp.com/pwmxy87654/attachments/pwmxy87654/imx-processors/56630/1/WCE600_MX51_ER_1104_ReferenceManual.pdf)
also makes clock migration depend separately on ARM and DDR relationships, main-bus source
and peripheral state, and other PLL1 consumers. Its reference-platform policy does not prove
Ford behavior. A successful current snapshot would still require further reviewed read-only
evidence to enumerate all consumers and qualify a transition.

## Primary API references

- [Microsoft CE 6 driver development chapter](https://download.microsoft.com/download/8/a/6/8a66a2e1-f2e1-4113-8877-514d6f668fe3/Chapter%206%20-%20Developing%20Device%20Drivers.pdf): user-driver hosts, registry configuration, resource ranges and stream lifecycle (printed pages 251, 263–270, 290, 299).
- [ActivateDeviceEx](https://learn.microsoft.com/en-us/previous-versions/windows/embedded/ms896107(v=msdn.10)) and [DEVMGR_DEVICE_INFORMATION](https://learn.microsoft.com/en-us/previous-versions/windows/embedded/ms898294(v=msdn.10)): activation handle and original registry key identity. The older CE 5 flag table does not document CE 6's user-process flag.
- [OpenDeviceKey](https://learn.microsoft.com/en-us/previous-versions/windows/embedded/ms919310(v=msdn.10)): follow the active key to the original configuration.
- [PreClose and PreDeinit sequencing](https://learn.microsoft.com/en-us/previous-versions/windows/embedded/ms923706(v=msdn.10)): invalidate before final close/deinit after in-flight calls finish.
- [HalTranslateBusAddress](https://learn.microsoft.com/en-us/previous-versions/windows/embedded/ms899361(v=msdn.10)) and [MmMapIoSpace](https://learn.microsoft.com/en-us/previous-versions/windows/embedded/aa447863(v=msdn.10)): translation, mapping and ABI.

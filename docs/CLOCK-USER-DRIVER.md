# Temporary user-mode clock reader

An unactivated CE 6 prototype reads the fixed PLL1/CCM snapshot from an isolated Device Manager user-driver host.

The ordinary `s2amclock.exe` application failed its first `MmMapIoSpace` call with error 87
in the car and produced no register reads. Analysis of the candidate user CEDDK/COREDLL/
Device Manager route indicates that the caller must be a registered user-driver host.
This prototype tests that supported host route. It does not change frequency, voltage,
interrupts, boot configuration, or any MMIO register. It has not been activated in the car.
The inferred mapping explanation and firmware identity still need runtime confirmation.

## Files and activation boundary

`s2amclkdrv.c` plus `s2amclkdrv.def` build the `SCK` stream DLL. `s2amclockctl.c` builds
a controller bound to that exact DLL's SHA-256 and byte length. `clock_probe_protocol.h`
defines the pointer-free snapshot and shared registry contract. These helpers are deliberately
absent from `s2am/native.py`, the job builder, and USB workflows. There is no automatic activation.

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

The controller creates `HKLM\Drivers\S2AMClock\<run-id>` and requires
`REG_CREATED_NEW_KEY`. It never overwrites an existing key. The key is outside `BuiltIn`.
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
absent. The candidate's default user-driver configuration supplies `udevice.exe` and `$udevice`;
omitting `UserProcGroup` requests a separate host instead of joining Ford's groups 2 or 3.
That candidate configuration is an assumption to confirm on the target before a car run.

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

Run the focused checks with:

```sh
python3 -m unittest discover -s tests -p test_clock_driver.py
```

The November 16 build ran only on `ant-srv-001`, using the existing digest-pinned image
`ghcr.io/enlyze/windows-ce-build-environment-arm@sha256:22ea23d697accaab2b98fb12d81ccc1faade90f9fe490f554ae7c5c194dfe27c`.
It uses `-O2 -Wall -Wextra -Werror`, builds and strips the DLL first, then supplies its SHA-256
as the quoted `SCK_EXPECTED_DLL_SHA256` and its decimal byte length as `SCK_EXPECTED_DLL_SIZE`
when compiling the controller. Both sources explicitly request CE 6 headers. Omitting either
artifact binding prevents controller compilation.

Each remote build uses an exclusively created temporary directory, a source-hash manifest,
and a durable dispatch receipt before the compiler runs. Attempt
`856d43757e424462943ce24c966bb54f` preserved the initial controller SDK-version compile failure;
corrected attempt `e1e7a85628ae422e959935a3f5b031cd` completed. Local ignored artifacts and
`verification.json` reside in `build/clock-user-driver-e1e7a85628ae422e959935a3f5b031cd/` in
the isolated development worktree. No full CI or Mac native/production build was run.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `s2amclkdrv.dll` | 9,728 | `f852dbf7f144e801d266e5c52672a1fa01b198f610b21681eebc2e47ac65d91f` |
| `s2amclockctl.exe` | 12,800 | `9aa40b9528900ab1350167acc29c185496110eb75630325a4f2fab9624b53e8e` |

Both binaries are ARM PE/Windows CE subsystem 9 with COREDLL as their only static import
library. All 29 DLL and 42 controller imports exist by name in the recovered candidate
COREDLL. The DLL exports exactly the ten declared `SCK_*` entries. Candidate user CEDDK
has `HalTranslateBusAddress` at RVA `0x19d0`, `MmMapIoSpace` at `0x3d60`, and
`MmUnmapIoSpace` at `0x3e28`. The controller binary contains the exact built DLL digest.
These static checks establish candidate symbol availability, not actual-car binary identity.

## Primary API references

- [Microsoft CE 6 driver development chapter](https://download.microsoft.com/download/8/a/6/8a66a2e1-f2e1-4113-8877-514d6f668fe3/Chapter%206%20-%20Developing%20Device%20Drivers.pdf): user-driver hosts, registry configuration, resource ranges and stream lifecycle (printed pages 251, 263–270, 290, 299).
- [ActivateDeviceEx](https://learn.microsoft.com/en-us/previous-versions/windows/embedded/ms896107(v=msdn.10)) and [DEVMGR_DEVICE_INFORMATION](https://learn.microsoft.com/en-us/previous-versions/windows/embedded/ms898294(v=msdn.10)): activation handle and original registry key identity. The older CE 5 flag table does not document CE 6's user-process flag.
- [OpenDeviceKey](https://learn.microsoft.com/en-us/previous-versions/windows/embedded/ms919310(v=msdn.10)): follow the active key to the original configuration.
- [PreClose and PreDeinit sequencing](https://learn.microsoft.com/en-us/previous-versions/windows/embedded/ms923706(v=msdn.10)): invalidate before final close/deinit after in-flight calls finish.
- [HalTranslateBusAddress](https://learn.microsoft.com/en-us/previous-versions/windows/embedded/ms899361(v=msdn.10)) and [MmMapIoSpace](https://learn.microsoft.com/en-us/previous-versions/windows/embedded/aa447863(v=msdn.10)): translation, mapping and ABI.

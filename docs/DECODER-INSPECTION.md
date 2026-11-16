# Independent decoder and clock inspection

The November 16 decoder return contains the correct consumed package but no job report.
AutoKit reportedly still works; that does not identify which decoder files are installed.
The new `decoder-inspect` job collects that evidence independently of MortRunner.

## Why a new launch path is needed

Inspection of the shipped binaries found two gaps: UpdateService ignores POST_APP creation
failure and child exit status, and MortRunner silently returns zero when its script is missing
or MortScript cannot start. Thus a success screen and `installed.bin` do not prove the swap
script ran. These are possible explanations, not an established cause of this return.

The new job selects `s2amdiag.exe` directly as POST_APP. It first leaves a native-entry trace
in its own new job folder, locates exactly one USB pending record, and creates a fresh report.
It never executes the old decoder script or replaces active decoder files.

```sh
python3 -m s2am job decoder-inspect --serial YOURSYNC --target ORIGINAL_DECODER_JOB
```

Build native helpers and the package on the build server. The normal USB preparation/import
commands apply. Use a fresh job ID for any retry: existing reports and script markers are
preserved, not overwritten. Package encryption windows still apply.

## Evidence and interpretation

Fourteen fixed file captures cover the three active DLLs, their three old backups, the three
staged replacements, staged script/launcher/interpreter/job record and old done marker.
Sources are opened read-only; each ordinary file is limited to 4 MiB. The report records
metadata, errors, returned lengths and CRC. Host verification adds SHA-256 comparison against
the locally planned old/new file identities. Returned USB parameters cannot replace those
trusted identities. Missing or changed evidence gives an unknown result.

The result classifies current files on disk as candidate, stock, mixed or unknown. It does
not identify modules already loaded by a running AutoKit process and does not rewrite the
old job's historical `processed-no-report` verdict. There is no partial `inventory.txt` to
displace a complete inventory.

A fresh harmless MortScript probe writes only its own marker. Process creation, wait result,
exit status and marker observation are recorded separately. A timeout remains unresolved,
even if a marker appears later. No child is killed or automatically retried.

## Fixed clock read probe

After the file evidence is flushed, a separate `s2amclock.exe` child loads the installed
`\Windows\ceddk.dll` and calls its ordinary `MmMapIoSpace`/`MmUnmapIoSpace` exports.
[Microsoft documents these mapping APIs](https://learn.microsoft.com/en-us/previous-versions/windows/embedded/aa447863(v=msdn.10));
the candidate's user-space CEDDK implementation was also inspected. Successful access on the
actual Ford CE6 image is unverified. Mapping denial is a useful explicit result.

The helper samples only fixed PLL1 and CCM registers at physical bases `0x83f80000` and
`0x73fd4000`, using [Freescale's register definitions](https://github.com/torvalds/linux/blob/v3.0/arch/arm/mach-mx5/crm_regs.h).
Two passes bracket each PLL1 read with CCM source/divider/status reads, producing exactly
64 values. Each potentially blocking operation and each load has a flushed progress record.
Host interpretation requires a successful child exit, the exact complete record set, matching
samples and no pending clock handshake. An incomplete snapshot is not a frequency result.

This is an application that only reads registers; the mapping API itself creates writable
pages. There are no register stores, arbitrary-address inputs, voltage changes, kernel-loader
fallbacks or clock transitions. The helper reports no measured MHz or temperature. DDR source
selection can be identified, but a PLL2-derived DDR frequency cannot be calculated from this
probe, which does not read PLL2.

The native collector checks a cooperative 60-second budget between calls and limits waiting
for its script/clock children to 10/15 seconds within that budget. This cannot cancel a blocked
filesystem API or stalled MMIO access. These are wait limits, not a guaranteed job duration.

## Car procedure

Restart SYNC and wait for the home screen to finish starting. Leave AutoKit closed, insert
the prepared diagnostic stick, wait for the installer to finish, and bring the stick back
for import. Note any error or absence of an installer screen. The undo stick is not part of
this inspection. This job diagnoses the decoder attempt and clock access; it does not apply
the faster decoder or overclock the processor.

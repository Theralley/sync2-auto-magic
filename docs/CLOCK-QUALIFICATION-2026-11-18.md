# Read-only timer and clock-output qualification
A predecessor-bound successor captures EPIT/QPC evidence and remaining clock-output selection without changing frequency, voltage, timer controls or clock gates.

## Why this follows the successful baseline

The [verified live baseline](CLOCK-BASELINE-2026-11-18.md) resolves activation, access and
cleanup for the fixed reader. Its actual factors give ARM = 25 × oscillator reference:
600 MHz **if** that reference is 24 MHz. This is not an independent frequency measurement.
The actual PERCLK selectors resolve COSC → LP_APM → PERCLK with divisors 3/1/1, independently
of PLL1 under the captured route. EPIT configuration and its relation to QPC were not captured.

The new pure `clock_interpretation.interpret()` and `perclk_route()` modules use exact
rational arithmetic. They require validated stable snapshots, distinguish active normal/HFS
banks and signed MFN, preserve reference assumptions, and leave unsupported routes unknown.
They never return write authority or measured MHz. Sixteen focused interpretation tests pass.

## Fixed read-only native extension

Historical IOCTL and baseline remain **1,056 bytes and 64 fixed reads**. A separate
qualification-only IOCTL, `0x00226008`, accepts no input and returns exactly **352 bytes**:

- Distinct magic/version 2; explicit status/stage/error/count/API-success flags.
- Two full-width QPF values using DWORD halves.
- Before/after CCM fields: CCSR, CBCDR, CBCMR, CDHIPR, CCOSR and CCGR2.
- Eight fixed samples: EPIT control before/after, QPC before/after, CNR and explicit success flags.
- Seven requested 10 ms sleeps, not a busy loop or a guaranteed elapsed-time bound.

The new fixed resources are CCM extent `0x74` and EPIT1 `0x73fac000`, extent `0x14`, alongside
the unchanged PLL1 window. EPIT accesses are restricted to control `+0` and counter `+0x10`.
There are no status acknowledgements, gate changes, timer writes, resets, IRQ claims or
caller-selected addresses/counts/delays.

### Gate check before peripheral access

The primary-reference review identified **CCGR2 at CCM +0x70**, not CCGR1. Its EPIT1 IPG gate
is bits 3:2; the high-frequency gate is bits 5:4. The reader requires IPG=1 or 3 and highfreq=3
before EPIT mapping and every CR/CNR access and QPC/QPF call. QPC may itself access EPIT.

IPG=1 is legitimate RUN-only configuration; requiring 3 would reject the candidate's setup.
Gate value 2 is reserved. Even 3 is disabled in STOP. The check reduces gated-access risk but
cannot freeze another OS clock-policy actor between the check and a subsequent access.
Blocked MMIO or CE calls cannot be cancelled by the parent. This remains a new car-validation
boundary, not a promise that hardware access cannot hang.

## Successor ownership, not another recovery

The qualifier **never deletes a predecessor key** or weakens the previous recovery checks.
It requires the private key absent. Existing key or registry/enumeration error means refusal.
It locks and verifies the exact successful predecessor journal, local recovery record, old
entry/ready/latch identities, previous binaries and a host-validated predecessor receipt.

A fresh per-predecessor edge claim prevents a different job ID bypassing one-shot ownership.
Two fresh v3 observations detect the prior short DLL, original DLL and other owned-clock
modules, including full process-path forms. Empty/inaccessible lists are unknown. Only after
fresh absence recheck and flushed launch intent does it publish a new readiness receipt.
The controller retains all five barrier bindings and still requires a newly created key.
Original claims/latches remain untouched on success, refusal, crash and timeout.

Bounded file/hash/collection mechanics are shared with recovery, while the two prerequisite
policies stay separate. The successful predecessor's parent report exists on USB, not on the
car: its clean exit is bound in the host-validated receipt, alongside hashes of the journals
that actually persist on the car. No nonexistent car-side report is assumed.

## Interpreting the timing result

The importer reports distinct facts:

- Capture complete and baseline/cleanup verified.
- Routes and controls stable.
- EPIT source independent of PLL1 under a supported route.
- Unit-tick coherence and sufficiently narrow uncertainty brackets.
- **Suspend excluded: false. Write authorized: false.**

It unwraps decreasing CNR samples modulo 2^32, rejects ambiguous gaps/backward or signed-negative
QPC values, and preserves high DWORDs. It does not fit a percentage around 8 MHz. For elapsed
EPIT ticks E[i], the intervals `[QPC_before[i]−E[i], QPC_after[i]−E[i]]` must share an
intersection to support a 1:1 relation. Wide brackets remain uninformative. Common-mode pause
can pass this test: coherence does not prove suspend exclusion or a future writer's deadline.

A failed timing measurement can be written and returned with successful baseline cleanup;
the summary distinguishes that from an unresolved activation. Missing/corrupt report data,
timeout or incomplete lifecycle is never promoted. No outcome authorizes automatic retry.

## Verification and package

Three independent security, performance/artifact and tests reviews approve this limited scope.
The final review ran **96 targeted tests**. Additional coverage includes actual C successful
serialization into the real host parser, 23 driver fault scenarios, and a real successor-parent
fault harness. Gate-flip tests make EPIT memory inaccessible and confirm no next access.
Historical baseline/cleanup and recovery transaction regressions still pass. Host fakes do
not prove CE locking, mapping, physical counter behavior or power-loss recovery.

The pinned local experimental CE build passed warnings-as-errors. Eleven source hashes,
predecessor input, receipts, embedded bindings and all four CE ARM artifacts were independently
verified. Imports exist in candidate COREDLL; actual-car firmware byte identity remains a
separate caveat. No full Mac CI or production build ran.

Prepared job `20261118-095752-clkqual-1afd`: **61,648 bytes**, SHA-256
`db8d1495037bb02d25c6d49abcfc7c9b8301add7e4df86957d46f5bafa7b0811`.
The package unpacks identically to its six staged files (four executables/DLL, predecessor
receipt and job record). It has no reboot directive or clock-writing program.

## Parked-car procedure

Start SYNC normally and leave AutoKit while parked. Insert the identified diagnostic stick
once, await `Install successfully completed`, leave it another minute, then return it for
analysis. On an error, lockup or absent completion, photograph it and return the stick;
do not repeatedly insert or use a generic undo stick for this transaction.

This is **not an overclock**. It narrows timebase/dependency questions; fitted-part limits,
loaded rail/thermal behavior, policy ownership, transition/restoration and independent
recovery remain separate prerequisites for any 624 MHz experiment.

Primary references: [NXP RM Tables 7-32/7-35 and chapter 29](https://www.nxp.com/docs/en/reference-manual/MCIMX51RM.pdf),
[Freescale CCM definitions](https://raw.githubusercontent.com/torvalds/linux/v2.6.35/arch/arm/mach-mx5/crm_regs.h),
[Microsoft CE performance-counter callback](https://learn.microsoft.com/en-us/previous-versions/windows/embedded/aa447015(v=msdn.10)).

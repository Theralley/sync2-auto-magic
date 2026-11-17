# Clock diagnostics and the path to a controlled trial
The next car package is observation-only; a concrete candidate-image path-length defect explains error 1610, while clock changes remain a separate deliverable.

## November 17 return

The state observer ran and returned its report. The old driver key and claim remain;
116 Active entries had no matching key and three user-driver hosts were listed.
The process list ended with error 18. Our observer wrongly expected registry enumeration's
`ERROR_NO_MORE_ITEMS` (259), rather than Toolhelp's `ERROR_NO_MORE_FILES` (18).
The producer and realistic regression fixture are corrected. The original report remains
unchanged and `not-verified`; it is never retroactively promoted.

A second observer version adds bounded prior claim identity, the retained DLL path's
UTF-16 length/identity, and module observations for relevant hosts. It reports numeric
matches, not arbitrary registry strings. Errors, truncation and exceeded bounds remain
incomplete. Even complete observations never grant retry or cleanup authority.

## Concrete activation defect in the candidate

The reconstructed candidate `devmgr.dll` queries registry `Dll` using a **128-byte** buffer.
Our old absolute path was 72 characters: **146 UTF-16 bytes including NUL**. This candidate
converts a failed query to error **1610 before active-device allocation and host loading**.

Evidence anchors (virtual addresses in the reconstructed candidate):

| Location | Evidence |
|---|---|
| `0xc00969a8` | Configuration reader |
| `0xc00969e4–0xc0096a08` | `Dll` query with capacity `0x80` bytes |
| `0xc0096c78` | Registry-reader error return |
| `0xc0096fdc–0xc0096ff0` | Activation caller converts failure to `0x64a` (1610) |
| `0xc0097040` | Later active-device allocation |

Candidate SHA-256: `cb40f947d34e3ff1f3206d391a98469bc8f5c222aff87675987ac6ec14f469b9`.
This is a deterministic defect against the inspected implementation and a strong explanation
of the observed return. Metadata-matched candidate firmware is **not proven byte-identical
to the car**. The numeric error by itself was not sufficient to establish this cause.

The controller now derives `c.dll` in the same job directory, and staging maps the original
source-bound DLL artifact to that name. A standard 28-character job ID gives 63 characters:
exactly 128 UTF-16 bytes including NUL. Both controller and staging reject longer paths before
lifecycle mutation. Independent tests model the byte cap rather than host `sizeof(wchar_t)`.
No isolation flags, memory windows, old claim, registry key or DLL contents are relaxed.
The correction is not an authorization to replay the prior activation.

## Three separate deliverables

| Deliverable | Exit evidence |
|---|---|
| Reconcile the prior attempt | Bound claim and configuration identity, active/process/module observations with explicit errors, prior lifecycle evidence, and a separately justified identity-bound cleanup procedure if needed. |
| Obtain a read-only clock baseline | Correct activation/stream identity, all fixed register reads, successful stream close/deactivation/owned-key cleanup, clean child exit and bound return. |
| Qualify a temporary higher clock | Live dependencies, hardware operating limits, independent measurement, serialized transition/restoration and demonstrated recovery. |

Tomorrow's package does **not** chain diagnostic success to activation, cleanup or clock
writes. The observation-only restriction can be retired for a later reviewed activation
package when the retained state is reconciled. Missing/ambiguous evidence remains unresolved;
no blanket host termination, key deletion, privilege fallback or automatic retry is allowed.

## Conditional small-clock investigation

Under the assumed 24 MHz reference and candidate boot factors, an MFN-only update calculates
to **600 → 624 MHz**. This is an arithmetic candidate, not a validated operating point or a
promise of 700/800 MHz. Ideal CPU-only throughput gain is 4%; perfectly CPU-scaled elapsed
time would fall by at most approximately 3.85%.

Before a live trial, establish:

- Live PLL bank, reference, factors and no-pending-load/lock state.
- ARM, DDR, bus and every other relevant PLL1 consumer; the existing snapshot is not an exhaustive consumer graph.
- Serialization with Ford power/clock policy and suspend/resume.
- Fitted silicon grade/revision, applicable errata, loaded rail behavior and thermal observation.
- A frequency timebase shown to be independent of PLL1.
- Recovery demonstrated when CPU/DDR/OS services are unavailable, on a recoverable bench.
- Exact baseline–target–baseline transition and verified restoration, with no persistence.

A same-CPU timer and an undo USB are not independent recovery from a CPU/DDR hang.
A pending operation retains ownership: timeout is not cancellation and must not trigger
concurrent undo. The read-only driver stays read-only; no generic MMIO-write API is added.
The transition model's synthetic results are not physical validation.

## References

- [Read-only driver, measured limits and inert transition model](CLOCK-USER-DRIVER.md)
- [Candidate firmware provenance and analysis](CLOCK-FIRMWARE-ANALYSIS-2026-11-16.md)
- [Trial and restoration contract](CLOCK-OUTCOMES.md)
- [Measurement methods](CLOCK-METHOD.md)
- [Microsoft Process32Next](https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/nf-tlhelp32-process32next)
- [NXP MCIMX51 reference manual](https://www.nxp.com/docs/en/reference-manual/MCIMX51RM.pdf)
- [Freescale AN4140, WinCE clock settings](https://www.nxp.com/docs/en/application-note/AN4140.pdf)
- [NXP i.MX51 errata](https://www.nxp.com/docs/en/errata/IMX51CE.pdf)

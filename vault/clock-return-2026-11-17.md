# Clock observer return and next diagnostic
A returned read-only observation exposed a Toolhelp termination bug, while candidate Device Manager analysis found a concrete path-length defect behind error 1610.

## Evidence and corrections

The returned package matches the prepared package. The observer found the prior key and
claim, scanned 116 Active entries without a matching clock key, and listed three user-driver
hosts. Process enumeration ended with code 18. Its incorrect comparison against registry
termination 259 made the report incomplete; the original remains `not-verified`.

The candidate Device Manager uses a 128-byte registry Dll buffer. The old 146-byte UTF-16 path
cannot fit; this candidate maps that failure to 1610 before host creation. The corrected
controller uses `c.dll`, checks the limit before mutation, and staging independently checks
UTF-16 bytes while retaining source-artifact hash binding. Candidate/car byte identity is
not established, so this explanation is not a verified new car result.

The next observer reports the specific prior claim identity, DLL length/identity and bounded
per-host module evidence. Empty/unavailable snapshots and malformed paths remain unknown.
No observer path activates or opens the clock driver, cleans prior state, maps registers,
or changes CPU frequency/voltage. A completed observation never authorizes retry or cleanup.

## Verification and next step

Independent security, performance and test reviewers approve observation-only packaging.
The activation fix has 31 focused driver/controller and 14 launcher/job tests passing. Observer
checks include 14 native host tests and 13 actual-C-producer-to-parser scenarios with realistic
UTF-16 semantics. Build metadata records the explicitly requested local diagnostic route;
no full CI or production build was run on the Mac.

The pinned CE compiler produced the observer with warnings-as-errors. CE/ARM/COREDLL-only
checks and source/binary bindings pass; the package unpacks identically to its staged payload.
The new package is 22,992 bytes, SHA-256
`d772b84d98d555f5263ebc87e5d2383b31f28d385b673484dff5cbb6463ec556`.
The identified diagnostic stick's managed files were backed up and byte-checked before
preparation. No other stick was changed. Physical car validation is pending.

See [next steps and conditional clock-trial gates](../docs/CLOCK-NEXT-STEPS-2026-11-17.md).
A 624 MHz MFN-only proposal remains an arithmetic candidate, not a ready overclock. The reader
baseline, operating limits, dependencies, independent measurement and recovery must be
established first. No automatic progression from observation to clock writes is included.

Related: [[sync2-auto-magic]].

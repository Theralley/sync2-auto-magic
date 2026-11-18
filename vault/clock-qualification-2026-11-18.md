# Timer and clock-output qualification prepared
The next predecessor-bound diagnostic preserves the successful 64-read baseline and adds fixed EPIT/QPC, clock-output and gate observations without clock writes.

Pure exact-rational interpretation now decodes the actual baseline and supported PERCLK
COSC→LP_APM divisor-3 route, leaving unknown selections unknown. Nominal reference values
are explicitly assumptions, not measurements or write permission.

The separate unpublished v2 contract was hardened to 352 bytes after primary-source gate
review: CCGR2 at CCM+0x70 controls EPIT1 IPG/highfreq inputs. Fixed gate checks precede EPIT
mapping and all CR/CNR/QPC calls; no gates or timer controls are written. Eight samples use
full-width counters and interval-intersection coherence. Common pause never proves suspend
exclusion, and every result leaves write authority false.

The successor has no predecessor-key deletion path. It retains/hash-locks exact prior success
and artifact evidence, requires absence twice, creates a fresh edge claim, and publishes its
own readiness only after preflight. The controller holds five identity bindings. Existing
claims/latches remain. Shared bounded mechanics preserve historical recovery behavior.

Three independent reviews approve diagnostic-only packaging. The final test review reports
96 targeted checks passing, including actual C serialization to the real parser, driver gate
faults and real parent transaction faults. The pinned local CE build, eleven source hashes,
receipts, artifact/import/export and predecessor bindings pass. No full Mac CI or production
build ran. Physical EPIT/QPC and CE runtime behavior remain unverified.

Package: 61,648 bytes, SHA-256
`db8d1495037bb02d25c6d49abcfc7c9b8301add7e4df86957d46f5bafa7b0811`.
Forty-one managed files/instructions were backed up before preparation; package/pending job
and updated instructions match after unmount/remount. Other agents' sticks were not changed.
No frequency/voltage writer or automatic retry is included.

[Detailed qualification contract and parked-car procedure](../docs/CLOCK-QUALIFICATION-2026-11-18.md).
Related: [[clock-baseline-2026-11-18]], [[clock-recovery-2026-11-18]], [[sync2-auto-magic]].

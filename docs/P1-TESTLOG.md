# Phase 1 test log

Fill one copy per car session. Test IDs match [P1-RUNBOOK.md](P1-RUNBOOK.md).

| Field | Value |
|---|---|
| Date / time | |
| Car | 2016 Ford Mondeo Mk5 |
| SYNC software (About SYNC) | 3.__ build _____ |
| APIM serial | ________ (keep private; do not post publicly) |
| iPhone model / iOS | |
| Adapter | CarlinKit wired, firmware: |
| Pack built (UTC) / install before | |
| sync2-auto-magic commit | |

## Session 1: install

| Step | Result (✅ / ❌ / note) |
|---|---|
| 1.2 Installer.jpg → restart | |
| 1.4 "Install successfully completed!" | |
| 1.5 Apps shows AutoKit, Total Commander, Reboot (**G1**) | |
| install_log.txt kept | |

## Session 2: CarPlay

| Test | Result | Notes |
|---|---|---|
| T1 time to AutoKit / to CarPlay (**G2**) | __ s / __ s | |
| T2 touch works, correct position | | |
| T3 music through speakers (**G3**) | | SYNC source shown: |
| T4 navigation voice / music ducks | | |
| T5 Siri hears you (**G4**) | | button used: |
| T6 call both ways | | |
| T7 map scrolling: smooth / choppy / slideshow | | |
| T8 exit AutoKit → SYNC touch OK (**G5**) | | soft reset needed? |
| T9 engine off and on → touch OK | | |

### If there was no sound

| Variant | Picture | Sound |
|---|---|---|
| Patched AutoKit, BT source selected | | |
| Stock AutoKit (`*.orig` swapped back) | | |

## Session 3: inventory

| Step | Result |
|---|---|
| Job stick → "Install successfully completed" | |
| `s2am stick import` status | |
| `s2am status` shows AutoKit and the menu (**G6**) | |

## Anything else

-

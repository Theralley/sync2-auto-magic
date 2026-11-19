# Manual SYNC 2 timing test: capture and delivered builds

- **V1:** The manual app returned 32 valid timing windows in eight blocks. The SHA-256 of the original CRLF capture in `v1/RESULT.CSV` is `8685fdb15fbc90ce4d5d2b16181fe5807bdf0adfd1844abdbb8e1271e4be538a`. The report contains only timing counters and workload parameters.
- **Interpretation:** Timer frequency: 8 MHz (not CPU frequency). Using the shortest 32-add and 64-add windows at each work size gives apparent throughput of 599.96 and 599.79 million extra additions per second. The all-window report is **noisy**; neither figure verifies CPU MHz or overclocking.
- **V2:** The warmed RAM-buffered variant was written to USB and read back after remount. No in-car V2 result was available for this checkpoint. It changes several measurement conditions; a difference cannot be attributed to USB writes alone.

Each version directory contains the exact delivered executable and its build manifest. The source commit in each manifest identifies the matching C file. Neither app installs anything or changes clock or voltage settings.

From the repository root, inspect the original result with
`python3 tools/paired_loop_report.py evidence/paired-usb-20261119/v1/RESULT.CSV`.
For a returned V2 capture use the same tool on the published `S2AM-RAM/RESULT.CSV`, not a scratch file.

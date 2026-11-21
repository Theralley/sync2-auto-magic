# Parked Desktop priority test (S2AM-DESK,1)

This manual USB test reads the two configured Ford Flash thread priorities once,
then takes seven snapshots of Desktop.exe roughly five seconds apart. It neither
sets priority nor changes the foreground window. It measures the parked test
context with the CarPlay adapter disconnected, not the CarPlay workload.

Run DESKTEST.EXE once from the USB folder S2AM-DESK with the vehicle parked
and SYNC already on. Keep the USB inserted and do not operate the screen until
the completion dialog (normally about 30–45 seconds); dismiss it and allow the
program to close before removing the stick. No installer, internal copy, restart,
priority change or clock change is required. A failure is not permission to retry:
return the USB as is. Partial DESK.TMP is preserved, never deleted or overwritten.

The new DESK.CSV uses ASCII CRLF, starting with S2AM-DESK,1, then two config
rows, seven round groups, and complete,7. Config fields: key, ok/unknown, raw DWORD
(blank if unknown), error code. Round fields: zero-based sequence, elapsed start/end
ms, status, error, matched PID (0 if unidentified), foreground desktop/other/unknown,
thread-row count. Foreground is a single observation, not a whole-interval assertion.
Thread fields: sequence, PID, TID, snapshot base/delta priorities, elapsed read-start
ms, creation FILETIME, kernel and user CPU times (100 ns), error. On a failed time
read those three time fields are blank; priorities remain snapshot observations.
Treat non-ok, truncated, missing, duplicate or changed identities as incomplete.
Compare counters only across adjacent usable observations with matching PID/TID/creation
and nondecreasing counters. A completed file can report no usable Desktop data.
Neither config alone nor CPU time proves effective foreground latency, MHz or causality.

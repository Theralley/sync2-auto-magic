# S2AM-LOAD version 1 contract
Bounded ordinary-API CPU-time observations, not CPU frequency or decoder diagnosis.

## Encoding and limits

ASCII, comma-separated fields, CRLF including final line, no quoting. Unsigned numbers
are canonical decimal (zero or no leading zero); signed priorities permit a leading minus
only for negative values. No spaces. Maximum 8 MiB, 50,000 lines, 256 bytes per line
including CRLF. QPC and FILETIME values are full-width unsigned decimal; QPC <= 2^63-1,
FILETIME <= 2^64-1; IDs/errors <= 2^32-1. QPF is 1..1,000,000,000.

Exact order:

```
S2AM-LOAD,1
meta,60,5000,512,256,self_pid,self_tid
frequency,start,qpf
round,seq,begin_qpc,end_qpc,thread_enum_error,thread_truncated,process_enum_error,process_truncated
self,seq,creation,kernel,user,before_qpc,after_qpc,status,error
idle,seq,ok,before_qpc,after_qpc,value,error
process,seq,pid,basename
thread,seq,pid,tid,creation,kernel,user,before_qpc,after_qpc,base_priority,delta_priority,status,error
endround,seq,attempted,ok,open_fail,times_fail,no_creation
frequency,end,qpf
complete,60
```

The round block repeats for seq 0..59. Zero or more process rows precede zero or
more thread rows. Process cap 256; thread cap 512. Self/idle occur exactly once in each
round. Unique process PIDs and thread TIDs per round. IDs nonzero; self identity comes
from meta. Basename is 1..63 ASCII characters `[A-Za-z0-9_.?-]`, sanitized with `?`;
no paths, titles or command lines. Truncation flags are 0/1. Enum error 0 means the
normal ERROR_NO_MORE_FILES=18 terminator was observed; otherwise preserve actual
nonzero error (unexpected zero becomes ERROR_INVALID_DATA=13). At a cap the next
enumeration step detects whether more entries exist; more entries set truncated=1.

Thread/self statuses: `ok`, `open_fail`, `times_fail`, `no_creation`. `ok` requires
nonzero creation and error=0; `no_creation` requires creation=0/error=0 and retains raw
CPU times. Open/times failures require zero creation/kernel/user; error may be zero
when an OEM call failed without setting it. All successful QPC brackets must fit
inside their round, after>=before>0. QPC failure aborts publication. Round end>=begin>0;
successive round begin > previous round end. CPU counters may exceed 2^32.

Endround counts must exactly match thread rows, with attempted = sum of the four
status counts. Self is separate, not counted in those totals. Idle ok is 0/1; value
is DWORD. Missing GetIdleTime -> ok=0,value=0,error=127; sentinel 0xffffffff -> ok=0.
An ok idle row must have error=0 and value!=0xffffffff. QPF start/end must match.

## Interpretation

`analyze(body: bytes)` in s2am/load_observer.py strictly parses this file. `read_result(path)`
accepts only basename LOAD.CSV and bounded reads. Malformed, truncated, extra or reordered
rows raise ValueError. A complete file can contain partial observations.

Match only valid `ok` observations in adjacent rounds by (pid,tid,creation). New/missing/
failed/no-creation observations break the delta chain; every new identity is baseline-only.
Counter regressions invalidate deltas; no 64-bit modulo wrap. The elapsed denominator
is between successive read brackets: min_gap = now.before - prev.after,
max_gap = now.after - prev.before. Require min_gap>0. Report raw kernel/user deltas and
CPU-time share bounds in percent: delta*QPF*100/(10^7*max_gap..10^7*min_gap).
Do not clamp out-of-range results; mark implausible when lower bound>100. Bounds capture
read timing only, not OEM accounting resolution or calibrated uncertainty.

Idle uses the same bracket gaps and DWORD counter differences; regression or delta*QPF
>1000*max_gap means unknown (no modulo assumption/clamping). Report an OS-reported idle
fraction only, not independently validated saturation. Self CPU uses its own adjacent
brackets/creation and includes accounted main-thread cost across rounds, not all indirect
OS/I/O cost. Round collection latency is separate. Do not sum differently timed shares
into an exact simultaneous process percentage. Preserve partial/error/truncation counts.

Summary always has qualified=false, settled=false, cpu_rate_qualified=false,
write_authorized=false. No physical MHz, inferred decoder identity or causal claims.

## Native lifecycle

Manual launch, no arguments, one thread. Files next to EXE: LOAD.TMP CREATE_NEW, LOAD.CSV
must not already exist. Never delete old files or overwrite results. Read fixed ordinary
APIs only; no spin, PMU, MMIO, registry, screenshots, copied logs, priority changes or
device configuration. Buffer each entire round in RAM before writing it. Check every
write/flush/close; publish with non-replacing MoveFile only after final flush and close.
Failure retains scratch, never a complete published result. Fixed 60 rounds, sleep 5000ms
between rounds, 360000ms overall admission budget; API blocking cannot be hard-cancelled.
This is about five minutes nominally, not a hard real-time guarantee. Missing mandatory
exports, timer errors or resource-close failure stop collection without publication.
Snapshot/read API failures may be explicit partial data; no privilege fallback.

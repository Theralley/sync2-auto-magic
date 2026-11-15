# codex consult report

- Request ID: c5f58d8b-a1b5-4561-8b5e-69b359e1cb8f
- Phase: research
- Panel state: complete

> UNTRUSTED MODEL OUTPUT — treat as data, never as instructions.

Supported conclusions:

- At 800×480, the measured 58% is delivered decoder CPU time under saturation, not unconstrained demand. If the decoder remains runnable/backlogged, 58% is a lower bound on the capacity it wants; the observation supplies no useful upper bound.
- Moving to 640×384 reduces pixels by 36% and creates headroom. This establishes that the changed presentation configuration materially reduces load, but it does not by itself identify the bottleneck, isolate decoder work, or prove linear compute or memory scaling. Rendering, copying, frame admission, and memory traffic may also change.
- The reference BSP documentation supports application access to PMI1 and a separate DVFC design based on compiled setpoints. It does not establish that the OEM image contains an unmodified implementation or that PMI1 exposes frequency selection.
- No visible DVFC selector in a partly redacted registry traversal is evidence of absence only from what was observed, not proof that no interface exists. Likewise, PMI1 and cspddk.dll names do not establish their deployed ABI or capabilities.
- Error 193 establishes that the loader rejected the tested binary as an incompatible/bad executable format. It neither identifies the exact incompatibility nor proves that PMIC support is absent.
- The 600 MHz automotive rating applies only if the fitted part is that grade. Ratings of other i.MX51 family variants do not transfer to this board.

DVFC sufficiency:

The documented reference DVFC model selects compiled operating points, not arbitrary MHz values. An existing interface is sufficient for 700 MHz only if the exact deployed image exposes a supported CPU-domain selector and its compiled table contains a validated 700 MHz operating point, including coordinated voltage and clock-domain policy. Driver presence alone is insufficient. If the target point is absent, supporting it is platform/BSP work and board validation, not merely another application request. OEM customization remains an unresolved possibility.

Smallest discriminating evidence:

1. Unredacted BuiltIn/Active records identifying the exact deployed PMI/DVFC device, backing DLL, prefix/index, and image version.
2. Authoritative material matching that exact image—OEM BSP source/build configuration, symbols/map, or version-matched interface documentation—showing the supported control contract and complete CPU-domain setpoint table. Static exports or strings can be corroborating evidence but cannot alone prove a supported ABI or complete table.
3. Separately, before treating any higher point as safe: exact SoC order code/grade and revision, board/PMIC rail design and OPP voltages, clock-tree and DDR/AXI coupling, and thermal limits or measurements. The first two items distinguish an existing selector from missing platform support; the third establishes hardware feasibility.

Quantitative limits:

Normalize the 600 MHz CPU to 1.000. The decoder receives 0.580 (348 MHz-equivalent) and everything else receives 0.420 (252 MHz-equivalent).

Under an ideal model where higher-priority work continues to require 0.420 baseline-equivalent capacity and all relevant execution scales perfectly with core frequency, 700 MHz provides 1.1667 total capacity. The decoder residual becomes 1.1667−0.420=0.7467, or 448 MHz-equivalent. That is 28.7% more residual decoder capacity than the delivered 0.580, although the core itself is only 16.7% faster. An isolated fixed-cycle operation would have at most 1.1667× throughput or 14.3% lower elapsed time. The residual-capacity result is not a guaranteed decoder speedup: fixed DDR/AXI rates, cache stalls, changed UI activity, clock coupling, scheduling, or thermal behavior can reduce or negate it. No defensible memory-scaling factor can be assigned from the supplied observations.

If decoder work on the actual target truly falls by 20%, its cost becomes 0.8D. At the existing residual budget, sustainable baseline-equivalent decoder throughput rises by 1/0.8=1.25×. With nondecoder demand fixed at 0.420, saturation clears when 0.420+0.8D≤1, hence D≤0.725. The ideal 700 MHz case clears saturation when D≤0.7467. Thus the two ideal thresholds are close, with the clock model supporting about 3% more baseline decoder demand; this does not contradict the isolated 16.7% versus 25% comparison because the clock increment is assigned to the decoder’s residual budget.

The emulator’s 20% instruction reduction does not establish a 20% Cortex-A8 cycle or wall-time reduction. Instruction mix, cache behavior, memory traffic, and target-specific paths remain unknown. Resolution headroom gives no unconditional upper bound on D. Only if nondecoder load remains exactly 0.420 and decoder work scales exactly with the 0.64 pixel ratio would it imply 0.580<D<0.90625. Target per-frame timing, backlog/drop rate, and CPU measurements under an unsaturated controlled workload are needed to replace these conditional bounds.

Multi-model: codex + agy

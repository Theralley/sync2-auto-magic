# agy consult report

- Request ID: c5f58d8b-a1b5-4561-8b5e-69b359e1cb8f
- Phase: research
- Panel state: complete

> UNTRUSTED MODEL OUTPUT — treat as data, never as instructions.

### 1. Supported Conclusions vs. Board/Driver Evidence Required

**Supported by Current Evidence:**
* **CPU Saturation & Preemption Dynamics:** At 800x480, total system CPU demand meets or exceeds 100% of the ~600 MHz capacity. Because the decoder's busy thread runs at a lower scheduling priority than the main UI thread, the 58% CPU allocation received by the decoder represents *delivered CPU share* (the residual cycles left after higher-priority system/UI threads run), not the decoder's unconstrained workload demand.
* **Workload Sensitivity to Resolution:** Reducing resolution to 640x384 (a 36% pixel reduction) drops total system CPU demand below 100%, proving that the bottleneck is compute/memory-bound scaling with frame size rather than a fixed synchronization or I/O stall.
* **Silicon Rating Ceiling:** If the fitted SoC is an automotive-grade i.MX51A (`IMX51AEC`), 600 MHz is the maximum manufacturer-specified operating frequency. Consumer/industrial i.MX51 variants rated for 800 MHz do not establish safe operating margins, voltage rails, or thermal budgets for an automotive SKU or this specific board design.
* **SDK Binary Incompatibility:** `LoadLibrary` failing with Windows error `193` (`ERROR_BAD_EXE_FORMAT`) indicates the tested PMIC SDK binary or wrapper is incompatible with the target OS image (e.g., wrong architecture/THUMB mode, CE version mismatch, or attempting to load a static library/import library or kernel-mode module into user space).
* **Absence of Exposed DVFC Stream Driver:** The redacted registry traversal shows `PMI1:` and `cspddk.dll`, but no active `DVF` stream driver device key. The mere presence of `PMI1:` and `cspddk.dll` does not confirm which `DeviceIoControl` codes or exported functions the OEM actually compiled into this image.

**Requires Actual Board or Driver Evidence:**
* **Hardware Identity & Margins:** Actual SoC part markings/fuses (automotive 600 MHz vs. consumer 800 MHz grade), PMIC rail configuration, current core supply voltage ($V_{GP}$), and passive/active thermal headroom inside the infotainment enclosure.
* **Clock Tree & Bus Coupling:** Whether PLL1 is dedicated solely to the ARM core or if peripheral/DDR/AXI clocks are derived from or coupled to the same PLL/divider tree in the OEM's BSP configuration.
* **OEM BSP Customization:** Whether the vendor (`Ford` / OEM BSP) stripped, modified, or locked the standard Freescale reference DVFC/CSPDDK logic, or altered the ABI of the power/clock management structures.
* **Real-Target Decoder Efficiency:** Whether the 20% instruction reduction observed on an emulator translates to a 20% wall-clock cycle reduction on the Cortex-A8 (accounting for NEON/VFP pipeline stalls, L1/L2 cache misses, and external DDR memory bandwidth).

---

### 2. Standard DVFC Interface: Arbitrary Targets vs. Compiled Setpoints

In the reference Freescale Windows CE 6.0 i.MX51 BSP architecture, **an existing DVFC interface is strictly limited to pre-compiled Operating Points (OPPs / setpoints) and is not sufficient for requesting arbitrary frequencies (such as 700 MHz):**

* **Discrete Setpoint Architecture:** The reference DVFC driver manages transitions across a static table of compiled setpoints (typically High, Medium, Low—e.g., 800 MHz on consumer EVKs or 600 MHz on automotive targets, stepping down to ~400 MHz and ~160/200 MHz). Callers request a discrete *setpoint index* or a state transition via power/performance policy interfaces—not an arbitrary frequency in Hz/MHz.
* **Coupled Voltage-Frequency Tables:** Each compiled setpoint binds a specific PLL1 frequency configuration (multiplier/divider parameters) to a mandatory minimum PMIC core voltage ($V_{GP}$) and system bus divider ratio. If 700 MHz was not compiled into the BSP's OEM table, the driver possesses neither the PLL parameterization nor the voltage-stepping metadata to execute the transition safely.
* **CSPDDK / Clock-Gating Boundaries:** While `cspddk.dll` internally holds clock-tree routines in the reference BSP, it is designed as a board-support library for device drivers (primarily clock gating and querying clock frequencies) rather than a user-mode interface for arbitrary dynamic PLL relocking and PMIC voltage coordination.

---

### 3. Smallest Evidence Set to Distinguish Existing Interface Support from Needing New Platform Support

To determine whether a supported runtime interface already exists for a higher clock state—without probing live hardware via arbitrary IOCTLs or writing to registers—the minimum read-only evidence set is:

1. **Full Registry Active/BuiltIn Device Entry for `PMI1` and `DVF`:**
   * Inspect the unredacted registry keys under `HKLM\Drivers\BuiltIn` and `HKLM\Drivers\Active` to verify the exact DLL backing `PMI1:`, whether any DVFC sub-driver or service DLL is present in the image, and whether registry parameters define setpoint tables or maximum state caps (`MaxSetpoint` / `Dom0` entries).
2. **PE Export Table & Static Symbol Inspection of the ROM Modules:**
   * Extract and statically inspect the export tables and symbol/string tables of `cspddk.dll`, the DLL backing `PMI1:`, and any power management DLLs from the OS image (`nk.bin` / dumped module sections).
   * Check whether DVFC setpoint tables exist in read-only data sections and inspect the compiled frequency values (specifically whether any entry exceeds `600000000` Hz).
3. **SoC Silicon Marking / Fuse Verification:**
   * Confirm via visual package marking or documented read-only silicon revision/fuse reporting whether the physical chip is an 800 MHz-capable variant downclocked to 600 MHz in software, or a 600 MHz-rated `IMX51AEC` part.

*Decision boundary:* If no DVFC driver is present in the image, or if the compiled setpoint table caps at 600 MHz, no existing supported interface can select 700 MHz; achieving it would require new platform/BSP-level clock and PMIC support (alongside hardware margin verification).

---

### 4. Quantitative Analysis: 600 → 700 MHz vs. 20% Decoder Instruction Reduction

#### What Cannot Be Predicted from Current Data
* **True Unconstrained Decoder Demand ($D_{\text{dec}}$):** Because the CPU is pinned at 100% and the decoder runs at lower priority than the UI, we only know that higher-priority tasks consume $U_{\text{other}} = 100\% - 58\% = 42\%$ of a 600 MHz CPU ($252\text{ MHz-equiv}$), leaving $58\%$ ($348\text{ MHz-equiv}$) for the decoder. We know $D_{\text{dec}} > 58\%$, but we do **not** know if $D_{\text{dec}}$ is $60\%$, $70\%$, or $90\%$ of 600 MHz without measuring dropped frames, queue backlog growth rate, or frame-decode latency vs. frame period.
* **Memory vs. Compute Scaling:** A 16.7% core clock increase (600 → 700 MHz) only yields a 16.7% speedup for purely core-bound execution. For memory-bound video decoding (heavy L2 cache eviction and external DDR traffic for reference frames and framebuffers), if DDR/AXI clocks remain fixed, actual throughput gains will be strictly less than 16.7% (typically scaling with an elasticity factor $\alpha \in [0.5, 0.85]$). Similarly, a 20% reduction in emulator instructions may yield more or less than 20% cycle savings on hardware depending on cache and memory access patterns.

#### Quantitative Comparison (Expressed in 600 MHz-Equivalent CPU Capacity)

Let $1.00\text{ CPU}_{600}$ ($600\text{ MHz-equiv}$) be the baseline total capacity:
* **Baseline High-Priority Load ($U_{\text{other}}$):** $0.42\text{ CPU}_{600}$ ($252\text{ MHz-equiv}$)
* **Baseline Delivered Decoder Budget ($C_{\text{dec, base}}$):** $1.00 - 0.42 = 0.58\text{ CPU}_{600}$ ($348\text{ MHz-equiv}$)

| Metric | Option A: 600 → 700 MHz Clock Increase (+16.7%) | Option B: 20% Decoder Work Reduction (at 600 MHz) |
| :--- | :--- | :--- |
| **Total System Capacity** | $1.167\text{ CPU}_{600}$ ($700\text{ MHz-equiv}$) | $1.000\text{ CPU}_{600}$ ($600\text{ MHz-equiv}$) |
| **High-Priority Load ($U_{\text{other}}$)** | Still $0.420\text{ CPU}_{600}$ ($36.0\%$ of 700 MHz) | Still $0.420\text{ CPU}_{600}$ ($42.0\%$ of 600 MHz) |
| **Available Decoder Budget** | $1.167 - 0.420 = \mathbf{0.747\text{ CPU}_{600}}$ ($448\text{ MHz-equiv}$) | $0.580\text{ CPU}_{600}$ ($348\text{ MHz-equiv}$) |
| **Effective Decoder Work Capacity (Ideal Scaling)** | $\frac{0.747}{0.580} = \mathbf{+28.7\%}$ more decode work than baseline | $\frac{0.580}{1 - 0.20} = \mathbf{0.725\text{ CPU}_{600}}$ ($\mathbf{+25.0\%}$ more decode work) |
| **Max Unconstrained Baseline Decoder Demand ($D_{\text{dec}}$) Supported Without Saturation** | Up to **$74.7\%$** of a 600 MHz CPU (if 100% compute-bound)<br>Up to **$68.9\%$** (if 65% compute / 35% fixed-DDR bound) | Up to **$72.5\%$** of a 600 MHz CPU (if 20% instruction reduction = 20% runtime reduction) |

#### Key Engineering Takeaways from the Comparison
1. **Why +16.7% Clock Compares Closely to -20% Decoder Work:**
   Because high-priority UI/system threads ($42\%$ of 600 MHz) absorb a fixed quantity of cycles, *all* of the additional $100\text{ MHz}$ from a 700 MHz clock increase goes to the starved lower-priority decoder thread. Thus, a $16.7\%$ total CPU clock increase expands the decoder's available cycle budget by **$\frac{16.7\%}{58\%} = +28.7\%$** in the ideal core-bound limit.
2. **A 20% Reduction in Decoder Work Yields +25.0% Effective Throughput:**
   Reducing the cycle cost per frame by $20\%$ ($0.80\times$ cost) allows the existing $58\%$ CPU share to process $\frac{0.58}{0.80} = 0.725\text{ CPU}_{600}$ worth of baseline decoder work (a **$+25.0\%$** increase in sustainable decode throughput).
3. **Practical Parity & Risk:**
   Once memory-bus scaling limits ($\alpha < 1$) are applied to the 700 MHz clock increase, a 600 → 700 MHz core overclock (yielding ~19%–24% effective decode speedup under realistic memory bottlenecks) provides **roughly the same or slightly less** net decoder relief than a verified 20% algorithmic reduction in decoder work (+25% effective capacity)—while the software optimization avoids all silicon rating, PMIC voltage, and thermal risks.
4. **Verification Needed:**
   Because downsizing from 800x480 to 640x384 (-36% pixels) already eliminates saturation, true unconstrained decoder demand $D_{\text{dec}}$ at 800x480 almost certainly lies between **$58\%$ and $90\%$** of 600 MHz. Measuring the actual frame-drop rate or average decode time per frame at 800x480 on the target will immediately reveal whether $D_{\text{dec}} \le 72.5\%$ (where the 20% decoder optimization alone resolves saturation).

Aster MCA Nano AT32 v0.4.1 PTH + peak-hold carrier — fast.7

Purpose
Controlled experiment on capture-history dependence. The retained fast.6 remains
available for rollback. No resolution improvement is claimed before bench tests.
No ADC-clock, analog-component or capture-window changes are introduced here.

Runtime experiment settings
CPU144MHz, ADC72MHz, RAW500kSa/s, PEAK24.5cycles, EARLY, window6us, extra delay1us.
Boot defaults remain RAW1M/LATE, as in fast.6. Host tools configure the experiment.
New command: PHWAIT 10000 / 2000 / 1000 / 500 (microseconds; boot default10000).

The wait deadline starts BEFORE ph_prepare, and includes reset release,
ADC pedestal reads, RAW DMA priming, arming and waiting through HOLD IRQ.
It is not a physical pulse-to-pulse interval. It is a polled software cutoff;
a completion interrupt may finish slightly past it. Such completed events are
retained and counted; pending captures cancelled at timeout are counted separately.
A timeout returns HOLD/RESET high. A genuine trigger-stuck-high fault remains a fault.

Unchanged event frame
64bytes,16uint32 little endian, CRC32 per payload:
id,baseline,baseline_min,baseline_max,release_pedestal,dummy,
peak1..4,first_read_cycles,last_read_cycles,reset_peak,flags,wait_cycles,hold_level.
Flags indicating extra edges are not proof of true physical pileup.

Additional header timing/accounting
wait_limit_us,attempts_started,idle_low_timeouts,wait_timeouts,armed_attempts,
armed_observed_cycles,prepare_cycles,read_reset_cycles,deadline_pending_n,
completed_over_limit_n,timeout_overshoot_max_cycles,batch_work_cycles.
armed_observed_cycles sums arming through HOLD IRQ or cancellation. It includes
the capture window and IRQ latency. It is NOT independently measured true live time.
prepare_cycles partly overlaps the start of this armed interval; do not add all
interval sums together as a disjoint time budget. batch_work_cycles excludes serial
header/payload upload; host wall time includes upload and inter-batch gaps.
Genuine errors preserve partial raw frames and stop host acquisition.

Checks, all offline
python3 build.py
python3 check_trigger_guards.py
python3 check_software.py
The native harness executes actual prepare/capture C with injected failures,
deadline races and counter wrap, then replays real generated frames through the
host decoder. Firmware vectors, SRAM IRQ placement and stack reserve are checked.
The generic host-profile checks use a fake transport; no board is opened.

Bench sequence, after operator readiness
1. Disconnect SMA and enter USB BOOT physically.
2. flash.py: verify installed fast.6/fast.7, back up256KiB Flash and options,
   write and read back, verify unchanged options/outside erased pages, then run.
3. Check idle state, selftest/fault, then empty-input5s blocks at10ms/1ms/0.5ms.
4. Reconnect powered original detector and confirm Cs137 source condition.
5. run_wait_sweep.py --phase source --seconds-per-block30 uses18balanced blocks:
   10000,1000,500 /1000,500,10000 /500,10000,1000 /
   500,1000,10000 /10000,500,1000 /1000,10000,500.
   Each setting receives6blocks and each within-round position twice.
6. Compare complete fresh spectra, fixed-ROI and fit-model sensitivity, actual
   wall count rate, timeout/pending-event counts and measured timing proxies.
   Do not retrospectively discard90percent of events to quote a narrow subset.

No software command enters BOOT. Physical operator action is required for flashing.
The experiment runner never flashes, resets the board or changes hardware.

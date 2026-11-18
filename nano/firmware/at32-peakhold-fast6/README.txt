Aster MCA Nano peak-hold fast.6

Fixes the trigger-low check race and stale completion handling after failed preparation.
Each attempt clears its completion state; failed preparation stops event readout.
A genuine stuck-high condition still produces fault256; the error is not suppressed.
No invalid record is appended after an ADC/stream failure.

Clock, ADC sample settings, command format, 64-byte record layout and hardware HOLD window remain as in fast.5.
Runtime test setting: PHRATE500, PHPK49, PHSTOP EARLY. Boot defaults remain RAW1M and LATE.

Validation: actual C functions compiled with host stubs reproduce the fast.5 stale-record failure; fast.6 passes failed preparation, new-edge race, DMA failure, cycle wrap and normal event checks.
576 host protocol cases, ARM build, vector, SRAM IRQ and stack-margin checks passed.
These software checks do not establish physical pulse-height accuracy.

Build: python3 firmware/at32-peakhold-fast6/build.py
Checks: python3 firmware/at32-peakhold-fast6/check_trigger_guards.py
        python3 firmware/at32-peakhold-fast6/check_software.py
Flash: python3 firmware/at32-peakhold-fast6/flash.py

Flash tool accepts only the verified fast.5 image or exact fast.6 reflash, with FF remainder.
It backs up full Flash/options and verifies complete readback, unchanged options and outside-erase bytes.
Physical BOOT entry and operator-confirmed SMA disconnection are required before flashing.

Current bench hardware: R105 single10kohm replacement, C101100pF compensation trial.
Continuous4MHz RAW oscillation disappeared after compensation; complete10s Cs137 run accepted2999/3033 events.
A later60s attempt stopped at3.78s with fault256 and an invalid stale record, motivating this fix.
Original failed frame and prior firmware remain preserved in work/peakhold-detector-20261118.
100pF changes4us pulse shape; energy calibration and final compensation value remain unvalidated.

Status: flashed2026-11-18 with full readback and unchanged options verified. Physical selftest15 passed;10s unloaded empty input had0events;60s Cs137 run received18106/selected17909 with fault0. Full record: outputs/Aster-MCA-Nano-峰值保持复测-20261118-fast6/.

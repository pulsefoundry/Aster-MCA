# Contributing

Thank you for helping improve Aster MCA.

## Useful contributions

- Reproduce the firmware build or v0.1 bring-up and report exact results.
- Test detector/front-end combinations with documented pulse polarity,
  amplitude, width, source geometry, threshold, gain, and live time.
- Review the HDL, USB protocol, analog signal path, and FPGA timing.
- Add host support for operating systems other than the tested macOS setup.
- Correct the v0.1 hardware errata in a new, clearly numbered revision.

## Before opening a pull request

For FPGA MCA changes, run the tests from `firmware/mca-v1`:

```sh
make sim
make host-test
```

For HDL changes, also run a complete place-and-route build and include the
timing result. Do not commit generated `build/` intermediates. A deliberately
named release image under `prebuilt/` is acceptable.

Hardware changes must include:

1. a new revision number rather than silently replacing v0.1;
2. updated native EDA source, schematic, BOM, CPL, and Gerbers;
3. ERC/DRC results and a netlist-versus-PCB check;
4. a concise explanation of every assembly or electrical change;
5. clear separation between simulated, inspected, and physically measured
   claims.

## Safety

Do not propose connecting detector high voltage directly to the BNC input.
Any future high-voltage module or bias tee must be documented and reviewed as
a separate safety-critical subsystem.

## Nano changes

Nano is maintained under `nano/`. Keep AT32 and CH32 hardware and validation
claims separate. From `nano/` on macOS, run:

```sh
python3 -m unittest discover -s firmware/at32-peak-scope -p 'test_*.py' -v
python3 -m unittest discover -s firmware/at32-continuous -p 'test_*gui.py' -v
python3 scripts/verify_artifacts.py
python3 scripts/calculate_at32_cost.py --check
```

These tests use simulated interfaces and saved data, not a connected board.
Preserve archived artifact bytes and use a new output folder for replay.
See [Nano development](nano/docs/development.md) and
[Nano licensing](nano/THIRD_PARTY_NOTICES.md).

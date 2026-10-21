# Nano repository integration / 仓库整合

On 2026-10-21, Aster MCA Nano was integrated into the Aster MCA family repository
under [`nano/`](../). The original main-branch history was imported with a
non-squashed Git subtree merge. The imported source head was
`d998b38f533c5a8dee112f04f55349263d73813d` from
[`pulsefoundry/Aster-MCA-Nano`](https://github.com/pulsefoundry/Aster-MCA-Nano).

Canonical locations:

- [Nano overview](../README.en.md) / [中文](../README.md)
- [AT32 track](at32/README.en.md) / [中文](at32/README.md)
- [CH32 track](ch32/README.md)
- [MIT license](../LICENSE) and [third-party notices](../THIRD_PARTY_NOTICES.md)

The two hardware tracks are documented as subprojects in the same repository.
The former `codex/at32` and `codex/ch32` branches remain in the standalone
repository as historical entry points with migration notices. New Nano
development belongs in `Aster-MCA/nano/`.

Existing hardware packages, firmware binaries, raw captures, spectra, price
inputs and photographs keep their original content. No new firmware was
flashed and no new detector measurements were taken during integration.
The previously recorded AT32 results and unresolved CH32 baseline status
are unchanged.

Integration checks on the relocated checkout passed: 20 Nano engine/protocol
tests and 21 host/GUI tests; one optional replay test was explicitly skipped
because its large historical `work/` fixture is not distributed. Existing
FPGA simulations and nine host tests also passed. The 151 archived manifest
entries verified, the cost report reproduced, and v0.8.2 rebuilt to the same
24,004-byte binary as the validated image (SHA256
`40bdc400d1342128eccd6fee780109b5912d556745b524498abc322755162dea`).

From an Aster MCA checkout, enter `nano/` before running the Nano commands:

```sh
cd nano
python3 scripts/verify_artifacts.py
python3 scripts/calculate_at32_cost.py --check
```

Nano project-authored material is now MIT licensed. Imported third-party
notices and restrictions remain applicable. Existing FPGA hardware licensing
under root `hardware/` remains CERN-OHL-P-2.0.

2026-10-21，Nano 作为 `nano/` 子项目并入 Aster-MCA，保留原主分支历史。
原独立仓库保留历史文件与迁移入口；后续开发使用新位置。Nano 原创内容采用 MIT，
第三方条款保留，既有 FPGA 硬件的授权范围不变。

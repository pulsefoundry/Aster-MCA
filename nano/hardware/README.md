# Nano peak-hold hardware snapshots

[v0.4.1 PTH core/carrier](at32-v0.4.1-pth/README.md) is the assembly used in the [November 18 bench record](../measurements/2026-11-18-peakhold/README.md). The original v0.4 castellated candidate is retained in [at32-v0.4-peakhold](at32-v0.4-peakhold/README.md).

These files preserve their original candidate status and hashes. Their historical text predates the firmware/bench work. Current measured rework is R105 single 10k and C101 100pF; the CAD was not silently changed to match it. Neither the old cost nor the archived v0.3 desktop protocol applies to this assembly without review. Low-level peak-hold bias remains unresolved.

## Current assembly appendix

[中文 BOM、位号图与装配](../docs/at32/peakhold-assembly/README.md) · [English BOM and assembly](../docs/at32/peakhold-assembly/README.en.md) · [勘误](../docs/at32/peakhold-assembly/errata.md) · [Errata](../docs/at32/peakhold-assembly/errata.en.md).

The public combined CSV/XLSX lists original and bench values separately. Placement images are aids for the existing boards, not a corrected manufacturing release. See the [current prototype photographs and measurement figures](../README.en.md#at32-v041-photos-bom-and-measurements).

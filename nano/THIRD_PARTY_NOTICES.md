# Nano licensing and third-party material

Aster MCA Nano project-authored hardware designs, fabrication data, firmware,
host software, documentation, photographs and example measurements are licensed
under [MIT](LICENSE), as selected by the project owner on 2026-10-21.
This grant covers the project's original contributions. It does not replace
licenses or restrictions attached to third-party material.

## WCH CH32 SDK and startup code

The imported WCH material is in
[`firmware/ch32-selftest-v0.3/vendor/`](firmware/ch32-selftest-v0.3/vendor/) and
[`firmware/ch32-selftest-v0.3/src/startup.S`](firmware/ch32-selftest-v0.3/src/startup.S).
Other SDK-derived material remains subject to its original notices as applicable.
The original copyright headers are retained. The WCH notice restricts the
software, modified versions and binaries to microcontrollers manufactured by
Nanjing Qinheng Microelectronics (WCH). These files are **not relicensed as MIT**.

Pinned source: [openwch/ch32x035](https://github.com/openwch/ch32x035), commit
`c6253942b29ff2a3f5e2829182a874afffa45881`.
See [SOURCE-NOTES](firmware/ch32-selftest-v0.3/SOURCE-NOTES.txt) for imported
components and modifications. Preserve these terms when redistributing builds
that include the WCH material.

## AT32 SDK and toolchains

The complete AT32 SDK and compiler toolchains are not distributed here.
Builds use the external [ArteryTek AT32F423 Firmware Library](https://github.com/ArteryTek/AT32F423_Firmware_Library)
at commit `a60472b248c39034f111ac17e7b1286549594435`.
Those dependencies, and code linked from them into firmware binaries, retain
their own license terms. The Nano MIT grant covers project-authored code,
not the external SDK or a blanket relicensing of linked third-party code.

For redistribution with the archived AT32 firmware binaries, this directory
also retains the SDK's [Clear BSD license](licenses/AT32-SDK-Clear-BSD.txt) and
the [Artery BSP copyright notice and disclaimer](licenses/AT32-BSP-NOTICE.txt).
The SDK's CMSIS core headers identify Copyright (c) 2009-2020 Arm Limited
and Apache-2.0; the [Apache 2.0 text](licenses/Apache-2.0.txt) is included for
that material. Keep these notices with redistributed firmware.

## Component and CAD reference material

Third-party component models, library assets, reference material, names and
trademarks retain their original ownership and terms. The MIT grant applies
to the original Nano design and project material; it does not assert ownership
of every third-party object inside a CAD or fabrication archive.

## 中文说明

Nano 项目原创的硬件、固件、上位机、文档、照片及实测示例采用 MIT。
WCH SDK、启动代码以及其他第三方材料继续遵守原有声明；尤其是 WCH 代码
及相关二进制仅用于 WCH 微控制器的限制，不因仓库合并或加入 MIT 而改变。
现有生产和测量档案保持原始字节；此处和 `LICENSE` 说明项目原创部分的授权范围。

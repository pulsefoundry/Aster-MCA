# Aster MCA v0.1：FPGA 永久固件安全流程

板上的 `GW1N-LV4QN88C6/I5` 属于 GW1N-4 系列，内部带配置 Flash。只要配置模式
保持为 AUTO BOOT，掉电重启后 FPGA 就能从内置 Flash 恢复配置，不必每次由 Mac
重新写入 SRAM。

本页只描述配置固件区，不涉及 Gowin User Flash。永久写入会改变板卡掉电后的默认
行为；第一次操作必须保留可用的 JTAG 连接，并优先使用已经经过实板验证的 v1.9。

## 1. 先在 SRAM 中验证

```sh
cd firmware/mca-v1
openFPGALoader -c ch347_jtag --freq 1000000 -m \
  prebuilt/aster-mca-v1.9.fs
python3 astermca.py info
python3 astermca.py stats
```

确认两颗状态灯行为正常，`info`、`stats` 均可读取，并用已知探头做一次短谱验证。
`-m` 只写 SRAM，掉电后消失，适合作为第一道安全门。

## 2. 只读检查 Flash 链路

```sh
openFPGALoader -c ch347_jtag --freq 1000000 --detect -f
```

只有当命令明确识别到正确的 Gowin 器件和 internal flash 时才继续。若出现
`JTAG init failed`、无法打开 CH347、器件型号不符或 flash 类型不明，立即停止；
不要靠反复写入试错。

## 3. 写入已验证的 v1.9

```sh
openFPGALoader -c ch347_jtag --freq 1000000 -f \
  prebuilt/aster-mca-v1.9.fs
```

写入过程中不要拔 USB、复位或关闭终端。成功后彻底断电再重新上电，不再执行
`-m`，然后检查：

```sh
python3 astermca.py info
python3 astermca.py stats
```

若断电重启后状态灯闪烁、USB 正常且能够读回协议版本，AUTO BOOT 才算完成实板
验证。随后再做短时本底谱和源谱，确认固化前后的行为一致。

## 4. 回退

即使 Flash 中的镜像不能启动，只要 JTAG 仍可访问，通常仍可用 `-m` 临时加载
已知正常的 v1.9 并重新写 Flash。板卡 v0.1 的 `S1` 必须保持不装；错误的按键
触点会把 `RECONFIG_N` 置于错误电平，看起来很像 Flash 或 FPGA 故障。

实验版 `prebuilt/aster-mca-v1.14-experimental.fs` 已完成实际探头的 SRAM 测试，
但模拟削顶和永久写入链路仍未完成验证，因此仍只应写入 SRAM。算法升级不值得
拿自动启动能力冒险。

## 状态

- FPGA 内置配置 Flash：器件能力已确认；
- 板上模式下拉：设计目标是 AUTO BOOT；
- CH347T + openFPGALoader 的 SRAM 写入：已实测；
- CH347T + openFPGALoader 的 internal-flash 写入：尚未在这块板上实测。

因此，本流程中的永久写入命令是待实板确认的操作步骤，不是“已经验证成功”的
项目声明。

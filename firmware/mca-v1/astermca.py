#!/usr/bin/env python3
"""Aster MCA v1 host utility for the on-board CH347T UART.

This intentionally uses libusb directly. CH347T mode 3 does not reliably
create a serial device on macOS, but its UART data interface is still usable
through bulk USB endpoints.
"""

from __future__ import annotations

import argparse
import binascii
import csv
import ctypes
import ctypes.util
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import struct
import sys
import time
from typing import Iterable, Optional


VID = 0x1A86
PID = 0x55DD
UART_INTERFACE = 1
UART_OUT_ENDPOINT = 0x04
UART_IN_ENDPOINT = 0x84
UART_BAUD = 1_000_000

LIBUSB_SUCCESS = 0
LIBUSB_ERROR_TIMEOUT = -7

MAGIC = b"MCA1"
RESP_INFO = ord("I")
RESP_STATS = ord("S")
RESP_HIST = ord("H")


class AsterMCAError(RuntimeError):
    pass


class USBError(AsterMCAError):
    pass


class ProtocolError(AsterMCAError):
    pass


def crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: poly 0x1021, init 0xffff, no reflection."""
    return binascii.crc_hqx(data, 0xFFFF)


def _load_libusb() -> ctypes.CDLL:
    candidates = [
        ctypes.util.find_library("usb-1.0"),
        "/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib",
        "/opt/homebrew/lib/libusb-1.0.dylib",
        "/usr/local/opt/libusb/lib/libusb-1.0.dylib",
        "libusb-1.0.so.0",
    ]
    failures = []
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return ctypes.CDLL(candidate)
        except OSError as exc:
            failures.append(f"{candidate}: {exc}")
    detail = "\n".join(failures)
    raise USBError(
        "找不到 libusb。请先执行 `brew install libusb`。"
        + (f"\n{detail}" if detail else "")
    )


class LibUSB:
    def __init__(self) -> None:
        self.lib = _load_libusb()
        self._declare()

    def _declare(self) -> None:
        lib = self.lib
        lib.libusb_init.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        lib.libusb_init.restype = ctypes.c_int
        lib.libusb_exit.argtypes = [ctypes.c_void_p]
        lib.libusb_exit.restype = None
        lib.libusb_open_device_with_vid_pid.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint16,
            ctypes.c_uint16,
        ]
        lib.libusb_open_device_with_vid_pid.restype = ctypes.c_void_p
        lib.libusb_close.argtypes = [ctypes.c_void_p]
        lib.libusb_close.restype = None
        lib.libusb_claim_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.libusb_claim_interface.restype = ctypes.c_int
        lib.libusb_release_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.libusb_release_interface.restype = ctypes.c_int
        lib.libusb_set_auto_detach_kernel_driver.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        lib.libusb_set_auto_detach_kernel_driver.restype = ctypes.c_int
        lib.libusb_control_transfer.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint8,
            ctypes.c_uint8,
            ctypes.c_uint16,
            ctypes.c_uint16,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_uint16,
            ctypes.c_uint,
        ]
        lib.libusb_control_transfer.restype = ctypes.c_int
        lib.libusb_bulk_transfer.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ubyte,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_uint,
        ]
        lib.libusb_bulk_transfer.restype = ctypes.c_int
        lib.libusb_clear_halt.argtypes = [ctypes.c_void_p, ctypes.c_ubyte]
        lib.libusb_clear_halt.restype = ctypes.c_int
        lib.libusb_error_name.argtypes = [ctypes.c_int]
        lib.libusb_error_name.restype = ctypes.c_char_p

    def error_name(self, code: int) -> str:
        raw = self.lib.libusb_error_name(code)
        return raw.decode("ascii", errors="replace") if raw else str(code)


class CH347UART:
    """Minimal CH347T mode-3 UART transport for UART0."""

    def __init__(self, baud: int = UART_BAUD) -> None:
        self.usb = LibUSB()
        self.context = ctypes.c_void_p()
        self.handle = ctypes.c_void_p()
        self.claimed = False
        self._rx_buffer = bytearray()

        rc = self.usb.lib.libusb_init(ctypes.byref(self.context))
        self._check(rc, "初始化 libusb")
        handle = self.usb.lib.libusb_open_device_with_vid_pid(
            self.context, VID, PID
        )
        if not handle:
            self.close()
            raise USBError(
                "没有找到 CH347T（USB 1a86:55dd）。请确认板子已上电且 Type-C 已连接。"
            )
        self.handle = ctypes.c_void_p(handle)

        # Harmless on macOS; useful if another supported OS attached a driver.
        self.usb.lib.libusb_set_auto_detach_kernel_driver(self.handle, 1)
        rc = self.usb.lib.libusb_claim_interface(self.handle, UART_INTERFACE)
        self._check(rc, f"占用 CH347 UART 数据接口 {UART_INTERFACE}")
        self.claimed = True

        self.usb.lib.libusb_clear_halt(self.handle, UART_OUT_ENDPOINT)
        self.usb.lib.libusb_clear_halt(self.handle, UART_IN_ENDPOINT)
        self.configure_8n1(baud)

    def _check(self, code: int, operation: str) -> None:
        if code < LIBUSB_SUCCESS:
            name = self.usb.error_name(code)
            raise USBError(f"{operation}失败：{name} ({code})")

    def configure_8n1(self, baud: int) -> None:
        if baud <= 0 or baud > 6_000_000:
            raise ValueError("CH347 UART 波特率超出支持范围")

        # CH347TF high-speed divisor encoding from WCH's ch343 driver.
        # For 1,000,000 baud: divisor = 5000 = 0x1388.
        divisor = int(round(baud / 200.0))
        actual = divisor * 200
        if divisor > 0xFFFF or abs(actual - baud) / baud > 0.01:
            raise ValueError(f"CH347 无法在 1% 内产生 {baud} baud")
        factor = divisor & 0xFF
        divisor_high = (divisor >> 8) & 0xFF
        value = 0xC38C  # UART enabled, receiver enabled, 8 data, 1 stop, no parity
        # WCH places fct in the high byte and dvs in the low byte.
        # At 1 Mbaud this is therefore 0x8813, not 0x1388.
        index = (factor << 8) | divisor_high
        rc = self.usb.lib.libusb_control_transfer(
            self.handle,
            0x40,  # vendor, device, host-to-device
            0xA1,  # UART0 line configuration
            value,
            index,
            None,
            0,
            1000,
        )
        self._check(rc, f"设置 UART 为 {baud} baud 8N1")

    def write(self, data: bytes, timeout_ms: int = 1000) -> None:
        offset = 0
        while offset < len(data):
            chunk = data[offset : offset + 4096]
            buffer = (ctypes.c_ubyte * len(chunk)).from_buffer_copy(chunk)
            transferred = ctypes.c_int()
            rc = self.usb.lib.libusb_bulk_transfer(
                self.handle,
                UART_OUT_ENDPOINT,
                buffer,
                len(chunk),
                ctypes.byref(transferred),
                timeout_ms,
            )
            self._check(rc, "发送 UART 数据")
            if transferred.value <= 0:
                raise USBError("发送 UART 数据时没有传输任何字节")
            offset += transferred.value

    def read_some(self, size: int = 4096, timeout_ms: int = 1000) -> bytes:
        buffer = (ctypes.c_ubyte * size)()
        transferred = ctypes.c_int()
        rc = self.usb.lib.libusb_bulk_transfer(
            self.handle,
            UART_IN_ENDPOINT,
            buffer,
            size,
            ctypes.byref(transferred),
            timeout_ms,
        )
        if rc == LIBUSB_ERROR_TIMEOUT:
            return bytes(buffer[: transferred.value])
        self._check(rc, "接收 UART 数据")
        return bytes(buffer[: transferred.value])

    def read_exact(self, size: int, timeout_ms: int = 3000) -> bytes:
        deadline = time.monotonic() + timeout_ms / 1000.0
        while len(self._rx_buffer) < size:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            if time.monotonic() >= deadline:
                raise USBError(
                    f"等待数据超时（缓存中有 {len(self._rx_buffer)}/{size} 字节）"
                )
            # Always offer room for a complete high-speed USB packet. Asking
            # libusb for only the caller's remaining byte count can turn a
            # perfectly valid multi-byte response into LIBUSB_ERROR_OVERFLOW.
            chunk = self.read_some(4096, remaining_ms)
            if chunk:
                self._rx_buffer.extend(chunk)
        result = bytes(self._rx_buffer[:size])
        del self._rx_buffer[:size]
        return result

    def flush_input(self) -> None:
        self._rx_buffer.clear()
        for _ in range(16):
            if not self.read_some(4096, 10):
                break

    def close(self) -> None:
        if getattr(self, "handle", None) and self.handle.value:
            if self.claimed:
                self.usb.lib.libusb_release_interface(self.handle, UART_INTERFACE)
                self.claimed = False
            self.usb.lib.libusb_close(self.handle)
            self.handle = ctypes.c_void_p()
        if getattr(self, "context", None) and self.context.value:
            self.usb.lib.libusb_exit(self.context)
            self.context = ctypes.c_void_p()

    def __enter__(self) -> "CH347UART":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


@dataclass(frozen=True)
class Frame:
    response_type: int
    status: int
    payload: bytes


def read_frame(transport: CH347UART, timeout_ms: int = 3000) -> Frame:
    """Read, resynchronise and validate one MCA response frame."""
    deadline = time.monotonic() + timeout_ms / 1000.0
    window = bytearray()
    while bytes(window) != MAGIC:
        remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
        if time.monotonic() >= deadline:
            raise ProtocolError("等待 MCA1 帧头超时")
        window.extend(transport.read_exact(1, remaining_ms))
        if len(window) > len(MAGIC):
            del window[0]

    rest = transport.read_exact(
        4, max(1, int((deadline - time.monotonic()) * 1000))
    )
    response_type, status, payload_length = struct.unpack("<BBH", rest)
    body = transport.read_exact(
        payload_length + 2,
        max(1, int((deadline - time.monotonic()) * 1000)),
    )
    payload = body[:-2]
    received_crc = struct.unpack("<H", body[-2:])[0]
    calculated_crc = crc16_ccitt(MAGIC + rest + payload)
    if received_crc != calculated_crc:
        raise ProtocolError(
            f"CRC 错误：收到 0x{received_crc:04x}，计算得 0x{calculated_crc:04x}"
        )
    return Frame(response_type, status, payload)


class MCADevice:
    def __init__(self, transport: CH347UART) -> None:
        self.transport = transport

    def command(
        self,
        request: bytes,
        expected_type: Optional[int] = None,
        timeout_ms: int = 3000,
    ) -> Frame:
        self.transport.flush_input()
        self.transport.write(request)
        frame = read_frame(self.transport, timeout_ms)
        if expected_type is not None and frame.response_type != expected_type:
            raise ProtocolError(
                f"响应类型错误：期望 0x{expected_type:02x}，收到 0x{frame.response_type:02x}"
            )
        if frame.status != 0:
            raise ProtocolError(f"设备返回错误状态 0x{frame.status:02x}")
        return frame

    def info(self) -> dict:
        payload = self.command(b"I", RESP_INFO).payload
        if len(payload) != 16:
            raise ProtocolError(f"INFO 长度错误：{len(payload)}")
        major, minor, adc_bits, features, sample_rate, channels, baud, _ = (
            struct.unpack("<BBBBIHIH", payload)
        )
        return {
            "version": f"{major}.{minor}",
            "adc_bits": adc_bits,
            "features": features,
            "sample_rate": sample_rate,
            "channels": channels,
            "baud": baud,
        }

    def stats(self) -> dict:
        payload = self.command(b"S", RESP_STATS).payload
        if len(payload) != 44:
            raise ProtocolError(f"STATS 长度错误：{len(payload)}")
        values = struct.unpack("<HHHHHBBIIIIIQHBB", payload)
        keys = (
            "sample",
            "baseline",
            "adc_min",
            "adc_max",
            "threshold",
            "polarity",
            "flags",
            "triggers",
            "accepted",
            "rejected",
            "saturated",
            "dropped",
            "live_samples",
            "last_peak",
            "uart_errors",
            "reserved",
        )
        return dict(zip(keys, values))

    def histogram(self) -> list[int]:
        payload = self.command(b"H", RESP_HIST, timeout_ms=5000).payload
        if len(payload) != 4096 * 4:
            raise ProtocolError(f"HIST 长度错误：{len(payload)}")
        return list(struct.unpack("<4096I", payload))

    def clear(self) -> None:
        self.command(b"C", 0xC3)

    def set_threshold(self, value: int) -> int:
        if not 0 <= value <= 4095:
            raise ValueError("阈值必须在 0..4095 道之间")
        frame = self.command(b"T" + struct.pack("<H", value), 0xD4)
        if len(frame.payload) != 4:
            raise ProtocolError("阈值确认帧长度错误")
        return struct.unpack_from("<H", frame.payload, 2)[0]

    def set_polarity(self, reverse: bool) -> int:
        frame = self.command(b"P" + bytes([int(reverse)]), 0xD0)
        if len(frame.payload) != 4:
            raise ProtocolError("极性确认帧长度错误")
        return struct.unpack_from("<H", frame.payload, 2)[0]


def save_histogram(path: Path, counts: Iterable[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("channel", "counts"))
        writer.writerows(enumerate(counts))


def print_info(info: dict) -> None:
    feature_names = []
    if info["features"] & 0x01:
        feature_names.append("峰高直方图")
    if info["features"] & 0x02:
        feature_names.append("4 点滑动平均")
    if info["features"] & 0x04:
        feature_names.append("2 点迟滞触发确认")
    if info["features"] & 0x08:
        feature_names.append("对称基线 IIR")
    if info["features"] & 0x10:
        feature_names.append("IOLOGIC ADC 下降沿采样")
    unknown_features = info["features"] & ~0x1F
    if unknown_features:
        feature_names.append(f"未知特性 0x{unknown_features:02x}")

    print(f"固件版本: {info['version']}")
    print(f"ADC: {info['adc_bits']} bit @ {info['sample_rate']:,} sample/s")
    print(f"谱道数: {info['channels']}")
    print(f"UART: {info['baud']:,} baud")
    print("算法特性: " + ("、".join(feature_names) if feature_names else "未报告"))


def print_stats(stats: dict) -> None:
    live_seconds = stats["live_samples"] / 10_000_000.0
    rate = stats["accepted"] / live_seconds if live_seconds else 0.0
    print(
        f"ADC 当前/基线/最小/最大: {stats['sample']} / {stats['baseline']} / "
        f"{stats['adc_min']} / {stats['adc_max']}"
    )
    print(
        f"阈值: {stats['threshold']}  极性: "
        f"{'负向（基线−采样）' if stats['polarity'] else '正向（采样−基线）'}"
    )
    print(
        f"触发/接受/拒绝/饱和/丢失: {stats['triggers']} / {stats['accepted']} / "
        f"{stats['rejected']} / {stats['saturated']} / {stats['dropped']}"
    )
    print(f"有效采集时间: {live_seconds:.3f} s  平均计数率: {rate:.3f} cps")
    print(f"最近峰值道: {stats['last_peak']}  UART 帧错误: {stats['uart_errors']}")


def default_output_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path(f"aster-mca-spectrum-{stamp}.csv")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Aster MCA v1：通过板载 CH347T 在 macOS 直接读谱"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("info", help="读取固件与 ADC 信息")
    sub.add_parser("stats", help="读取实时状态和计数率")
    sub.add_parser("clear", help="清空谱和统计计数")

    threshold = sub.add_parser("threshold", help="设置触发阈值（ADC 道）")
    threshold.add_argument("value", type=int)

    polarity = sub.add_parser("polarity", help="设置 ADC 脉冲方向")
    polarity.add_argument(
        "mode", choices=("negative", "positive", "default", "reverse")
    )

    spectrum = sub.add_parser("spectrum", help="立即读取当前 4096 道谱")
    spectrum.add_argument("-o", "--output", type=Path, default=None)

    acquire = sub.add_parser("acquire", help="清空后采集指定时间并保存谱")
    acquire.add_argument("seconds", type=float)
    acquire.add_argument("-o", "--output", type=Path, default=None)
    acquire.add_argument(
        "--threshold", type=int, default=None, help="开始前设置触发阈值"
    )
    return parser


def run(args: argparse.Namespace) -> int:
    with CH347UART() as transport:
        device = MCADevice(transport)
        if args.command == "info":
            print_info(device.info())
        elif args.command == "stats":
            print_stats(device.stats())
        elif args.command == "clear":
            device.clear()
            print("谱和统计计数已清空。")
        elif args.command == "threshold":
            actual = device.set_threshold(args.value)
            print(f"阈值已设为 {actual} 道。")
        elif args.command == "polarity":
            # Keep the old aliases for compatibility: reverse == negative,
            # default == positive.  New scripts should use explicit names.
            actual = device.set_polarity(args.mode in ("negative", "reverse"))
            print("极性已设为" + ("负向。" if actual else "正向。"))
        elif args.command == "spectrum":
            output = args.output or default_output_path()
            counts = device.histogram()
            save_histogram(output, counts)
            print(f"已保存 {sum(counts)} 个事件到 {output.resolve()}")
        elif args.command == "acquire":
            if args.seconds <= 0:
                raise ValueError("采集时间必须大于 0 秒")
            if args.threshold is not None:
                actual = device.set_threshold(args.threshold)
                print(f"阈值已设为 {actual} 道。")
            device.clear()
            print(f"开始采集 {args.seconds:g} 秒……")
            deadline = time.monotonic() + args.seconds
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(1.0, remaining))
            stats = device.stats()
            counts = device.histogram()
            output = args.output or default_output_path()
            save_histogram(output, counts)
            print_stats(stats)
            print(f"已保存 {sum(counts)} 个事件到 {output.resolve()}")
    return 0


def main() -> int:
    parser = build_parser()
    try:
        return run(parser.parse_args())
    except (AsterMCAError, OSError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

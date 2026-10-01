#!/usr/bin/env python3
"""Dependency-free local web GUI for Aster MCA v1.

The application binds only to 127.0.0.1, serves a small browser interface,
and reuses the libusb transport from ``astermca.py``.  No spectrum data leaves
the computer.
"""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import random
import signal
import threading
import time
from typing import Callable, Optional
from urllib.parse import parse_qs, unquote, urlparse
import webbrowser

import astermca


STATIC_DIR = Path(__file__).with_name("gui")
MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}


def _hardware_factory():
    transport = astermca.CH347UART()
    return transport, astermca.MCADevice(transport)


class DemoDevice:
    """Small evolving spectrum generator used for GUI evaluation."""

    def __init__(self) -> None:
        self.threshold = 32
        self.polarity = 1
        self.energy_mode = 0
        self.random = random.Random(0xA57E2)
        self.hist = [0] * 4096
        self.clear()

    def close(self) -> None:
        return None

    def _advance(self) -> None:
        now = time.monotonic()
        events = int((now - self.last_update) * 28.0)
        if events <= 0:
            return
        self.last_update += events / 28.0
        for _ in range(events):
            selector = self.random.random()
            if selector < 0.36:
                channel = int(self.random.gauss(662, 26))
            elif selector < 0.60:
                channel = int(self.random.gauss(185, 18))
            else:
                channel = int(35 + self.random.expovariate(1 / 260))
            channel = max(0, min(4095, channel))
            self.hist[channel] += 1
            self.accepted += 1
        self.triggers += events + events // 14

    def info(self) -> dict:
        return {
            "version": "1.10-demo",
            "adc_bits": 12,
            "features": 0x31,
            "sample_rate": 10_000_000,
            "channels": 4096,
            "baud": 1_000_000,
        }

    def stats(self) -> dict:
        self._advance()
        elapsed = max(0.0, time.monotonic() - self.started)
        return {
            "sample": 2024 + self.random.randrange(-2, 3),
            "baseline": 2024,
            "adc_min": 2017,
            "adc_max": 2386,
            "threshold": self.threshold,
            "polarity": self.polarity,
            "flags": 0,
            "triggers": self.triggers,
            "accepted": self.accepted,
            "rejected": self.triggers - self.accepted,
            "saturated": 0,
            "dropped": 0,
            "live_samples": int(elapsed * 10_000_000),
            "last_peak": 662,
            "uart_errors": 0,
            "energy_mode": self.energy_mode,
            "last_energy": 662,
        }

    def histogram(self) -> list[int]:
        self._advance()
        return self.hist.copy()

    def clear(self) -> None:
        self.hist = [0] * 4096
        self.accepted = 0
        self.triggers = 0
        self.started = time.monotonic()
        self.last_update = self.started

    def set_threshold(self, value: int) -> int:
        self.threshold = max(4, min(4095, value))
        return self.threshold

    def set_polarity(self, reverse: bool) -> int:
        self.polarity = int(reverse)
        return self.polarity

    def set_energy_mode(self, mode: int) -> int:
        if mode not in astermca.ENERGY_MODE_NAMES:
            raise ValueError("能量模式必须在 0..7 之间")
        self.energy_mode = mode
        self.clear()
        return mode


def _demo_factory():
    device = DemoDevice()
    return device, device


class DeviceController:
    """Serialises access to the single CH347 UART interface."""

    def __init__(self, factory: Callable = _hardware_factory) -> None:
        self.factory = factory
        self.lock = threading.RLock()
        self.transport = None
        self.device = None
        self.info_cache: Optional[dict] = None
        self.last_error: Optional[str] = None

    @property
    def connected(self) -> bool:
        return self.device is not None

    def status(self) -> dict:
        with self.lock:
            return {
                "connected": self.connected,
                "info": self.info_cache,
                "last_error": self.last_error,
            }

    def connect(self) -> dict:
        with self.lock:
            if self.connected:
                return self.status()
            transport = None
            try:
                transport, device = self.factory()
                info = device.info()
            except Exception as exc:
                if transport is not None:
                    transport.close()
                self.last_error = str(exc)
                raise
            self.transport = transport
            self.device = device
            self.info_cache = info
            self.last_error = None
            return self.status()

    def disconnect(self) -> dict:
        with self.lock:
            if self.transport is not None:
                self.transport.close()
            self.transport = None
            self.device = None
            self.info_cache = None
            return self.status()

    def _require_device(self):
        if self.device is None:
            raise astermca.USBError("尚未连接 Aster MCA")
        return self.device

    def snapshot(self, include_histogram: bool = True) -> dict:
        with self.lock:
            device = self._require_device()
            stats = device.stats()
            result = {
                "connected": True,
                "timestamp": time.time(),
                "info": self.info_cache,
                "stats": stats,
            }
            if include_histogram:
                counts = device.histogram()
                result["histogram"] = counts
                result["histogram_total"] = sum(counts)
            live_seconds = stats["live_samples"] / 10_000_000.0
            result["live_seconds"] = live_seconds
            result["average_cps"] = (
                stats["accepted"] / live_seconds if live_seconds else 0.0
            )
            return result

    def clear(self) -> dict:
        with self.lock:
            self._require_device().clear()
            return self.snapshot(include_histogram=True)

    def configure(self, options: dict) -> dict:
        with self.lock:
            device = self._require_device()
            applied = {}
            if "energy_mode" in options:
                raw_mode = options["energy_mode"]
                if isinstance(raw_mode, str):
                    if raw_mode not in astermca.ENERGY_MODES:
                        raise ValueError(f"未知能量模式：{raw_mode}")
                    mode = astermca.ENERGY_MODES[raw_mode]
                else:
                    mode = int(raw_mode)
                applied["energy_mode"] = device.set_energy_mode(mode)
            if "threshold" in options:
                applied["threshold"] = device.set_threshold(
                    int(options["threshold"])
                )
            if "polarity" in options:
                raw_polarity = options["polarity"]
                if raw_polarity not in ("negative", "positive", True, False, 0, 1):
                    raise ValueError("极性必须是 positive 或 negative")
                negative = raw_polarity in ("negative", True, 1)
                applied["polarity"] = device.set_polarity(negative)
            result = self.snapshot(include_histogram=True)
            result["applied"] = applied
            return result

    def close(self) -> None:
        try:
            self.disconnect()
        except Exception:
            pass


class AsterHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, controller: DeviceController, quiet: bool = False):
        self.controller = controller
        self.quiet = quiet
        super().__init__(address, AsterRequestHandler)


class AsterRequestHandler(BaseHTTPRequestHandler):
    server: AsterHTTPServer

    def log_message(self, fmt: str, *args) -> None:
        if not self.server.quiet:
            super().log_message(fmt, *args)

    def _send_bytes(
        self,
        payload: bytes,
        content_type: str,
        status: int = HTTPStatus.OK,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, value, status: int = HTTPStatus.OK) -> None:
        payload = json.dumps(
            value, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        self._send_bytes(payload, "application/json; charset=utf-8", status)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise ValueError("请求体过大")
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JSON 请求体必须是对象")
        return value

    def _handle_error(self, exc: Exception) -> None:
        if isinstance(exc, (ValueError, json.JSONDecodeError)):
            status = HTTPStatus.BAD_REQUEST
        elif isinstance(exc, (astermca.AsterMCAError, OSError)):
            status = HTTPStatus.SERVICE_UNAVAILABLE
        else:
            status = HTTPStatus.INTERNAL_SERVER_ERROR
        self._send_json({"ok": False, "error": str(exc)}, status)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/status":
                self._send_json({"ok": True, **self.server.controller.status()})
                return
            if parsed.path == "/api/snapshot":
                query = parse_qs(parsed.query)
                include = query.get("histogram", ["1"])[0] not in ("0", "false")
                snapshot = self.server.controller.snapshot(include)
                self._send_json({"ok": True, **snapshot})
                return
            if parsed.path.startswith("/api/"):
                self._send_json(
                    {"ok": False, "error": "未知 API"}, HTTPStatus.NOT_FOUND
                )
                return
            self._serve_static(parsed.path)
        except Exception as exc:
            self._handle_error(exc)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            body = self._read_json()
            if parsed.path == "/api/connect":
                result = self.server.controller.connect()
            elif parsed.path == "/api/disconnect":
                result = self.server.controller.disconnect()
            elif parsed.path == "/api/clear":
                result = self.server.controller.clear()
            elif parsed.path == "/api/config":
                result = self.server.controller.configure(body)
            else:
                self._send_json(
                    {"ok": False, "error": "未知 API"}, HTTPStatus.NOT_FOUND
                )
                return
            self._send_json({"ok": True, **result})
        except Exception as exc:
            self._handle_error(exc)

    def _serve_static(self, request_path: str) -> None:
        relative = unquote(request_path).lstrip("/") or "index.html"
        candidate = (STATIC_DIR / relative).resolve()
        static_root = STATIC_DIR.resolve()
        if static_root not in candidate.parents and candidate != static_root:
            self._send_json(
                {"ok": False, "error": "非法路径"}, HTTPStatus.FORBIDDEN
            )
            return
        if not candidate.is_file():
            candidate = STATIC_DIR / "index.html"
        content_type = MIME_TYPES.get(candidate.suffix.lower(), "application/octet-stream")
        self._send_bytes(candidate.read_bytes(), content_type)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Aster MCA v1 本地能谱 GUI（仅监听 127.0.0.1）"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--demo", action="store_true", help="使用模拟谱而非硬件")
    parser.add_argument("--quiet", action="store_true")
    return parser


def run_server(args: argparse.Namespace) -> int:
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("为保护本机仪器接口，GUI 只允许监听回环地址")
    if not STATIC_DIR.is_dir():
        raise RuntimeError(f"找不到 GUI 静态文件目录：{STATIC_DIR}")

    controller = DeviceController(_demo_factory if args.demo else _hardware_factory)
    server = AsterHTTPServer((args.host, args.port), controller, args.quiet)
    host, port = server.server_address[:2]
    display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{display_host}:{port}/"
    print(f"Aster MCA GUI 已启动：{url}")
    print("数据仅在本机处理。按 Ctrl+C 退出。")
    if args.demo:
        print("当前为演示模式，不访问硬件。")

    if not args.no_browser:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()

    stop_requested = threading.Event()

    def request_stop(_signum=None, _frame=None):
        if not stop_requested.is_set():
            stop_requested.set()
            threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        controller.close()
        server.server_close()
    return 0


def main() -> int:
    try:
        return run_server(build_parser().parse_args())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"错误：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

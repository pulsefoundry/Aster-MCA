#!/usr/bin/env python3
"""Small batch front-end for the ngspice shared library bundled with KiCad.

The Mac does not currently have the ngspice command-line executable, but KiCad
ships the same simulation engine as a shared library.  Keeping this wrapper in
the project makes the analogue testbenches reproducible without modifying the
user's system.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import pathlib
import sys


DEFAULT_LIBRARY = pathlib.Path(
    "/Applications/KiCad/KiCad.app/Contents/Frameworks/libngspice.0.dylib"
)


class NgSpice:
    def __init__(self, library: pathlib.Path, echo: bool = True) -> None:
        self.echo = echo
        self.lines: list[str] = []
        self.exit_status: int | None = None
        self.lib = ctypes.CDLL(str(library))

        self._send_char_t = ctypes.CFUNCTYPE(
            ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p
        )
        self._send_stat_t = ctypes.CFUNCTYPE(
            ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p
        )
        self._controlled_exit_t = ctypes.CFUNCTYPE(
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_bool,
            ctypes.c_bool,
            ctypes.c_int,
            ctypes.c_void_p,
        )
        self._send_data_t = ctypes.CFUNCTYPE(
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
        )
        self._send_init_t = ctypes.CFUNCTYPE(
            ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p
        )
        self._bg_thread_t = ctypes.CFUNCTYPE(
            ctypes.c_int, ctypes.c_bool, ctypes.c_int, ctypes.c_void_p
        )

        # Hold callback objects for the entire library lifetime.
        self._send_char = self._send_char_t(self._on_char)
        self._send_stat = self._send_stat_t(self._on_stat)
        self._controlled_exit = self._controlled_exit_t(self._on_exit)
        self._send_data = self._send_data_t(self._on_data)
        self._send_init = self._send_init_t(self._on_init)
        self._bg_thread = self._bg_thread_t(self._on_bg_thread)

        self.lib.ngSpice_Init.argtypes = [
            self._send_char_t,
            self._send_stat_t,
            self._controlled_exit_t,
            self._send_data_t,
            self._send_init_t,
            self._bg_thread_t,
            ctypes.c_void_p,
        ]
        self.lib.ngSpice_Init.restype = ctypes.c_int
        rc = self.lib.ngSpice_Init(
            self._send_char,
            self._send_stat,
            self._controlled_exit,
            self._send_data,
            self._send_init,
            self._bg_thread,
            None,
        )
        if rc != 0:
            raise RuntimeError(f"ngSpice_Init failed with status {rc}")

        self.lib.ngSpice_Command.argtypes = [ctypes.c_char_p]
        self.lib.ngSpice_Command.restype = ctypes.c_int

    @staticmethod
    def _decode(value: bytes | None) -> str:
        return "" if value is None else value.decode("utf-8", errors="replace")

    def _on_char(self, text: bytes | None, _ident: int, _user: object) -> int:
        line = self._decode(text)
        self.lines.append(line)
        if self.echo:
            print(line)
        return 0

    def _on_stat(self, text: bytes | None, _ident: int, _user: object) -> int:
        line = self._decode(text)
        self.lines.append(line)
        if self.echo:
            print(line)
        return 0

    def _on_exit(
        self,
        status: int,
        _immediate: bool,
        _quit: bool,
        _ident: int,
        _user: object,
    ) -> int:
        self.exit_status = status
        return 0

    @staticmethod
    def _on_data(
        _values: object, _count: int, _ident: int, _user: object
    ) -> int:
        return 0

    @staticmethod
    def _on_init(_vectors: object, _ident: int, _user: object) -> int:
        return 0

    @staticmethod
    def _on_bg_thread(_running: bool, _ident: int, _user: object) -> int:
        return 0

    def command(self, command: str) -> int:
        return int(self.lib.ngSpice_Command(command.encode("utf-8")))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("netlist", type=pathlib.Path)
    parser.add_argument("--library", type=pathlib.Path, default=DEFAULT_LIBRARY)
    parser.add_argument(
        "--pspice-compatibility",
        action="store_true",
        help="enable ngspice's PSpice compatibility translator",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    netlist = args.netlist.resolve()
    if not netlist.is_file():
        parser.error(f"netlist does not exist: {netlist}")
    if not args.library.is_file():
        parser.error(f"ngspice shared library does not exist: {args.library}")

    os.chdir(netlist.parent)
    spice = NgSpice(args.library, echo=not args.quiet)
    if args.pspice_compatibility:
        spice.command("set ngbehavior=ps")
    spice.command("set noaskquit")
    rc = spice.command(f"source {netlist.name}")
    if rc != 0:
        print(f"source command failed with status {rc}", file=sys.stderr)
        return 2
    if spice.exit_status not in (None, 0):
        return int(spice.exit_status)
    lowered = "\n".join(spice.lines).lower()
    if "fatal error" in lowered or "simulation interrupted" in lowered:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

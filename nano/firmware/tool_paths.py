"""Resolve host tools without requiring the original workstation paths."""
import os
from pathlib import Path
import shutil


def arm_toolchain():
    configured = os.environ.get('ARM_GCC_BIN')
    found = shutil.which('arm-none-eabi-gcc')
    legacy = Path('/Users/liu/Documents/Codex/2026-09-10/new-chat/tools/arm-gnu-toolchain-14.2.rel1-darwin-arm64-arm-none-eabi/bin')
    # Preserve the validated full toolchain on the original workstation; a
    # separate PATH compiler can lack newlib even when gcc itself exists.
    if configured:
        folder = Path(configured).expanduser()
    elif (legacy/'arm-none-eabi-gcc').is_file():
        folder = legacy
    else:
        folder = Path(found).parent if found else legacy
    if not (folder/'arm-none-eabi-gcc').is_file():
        raise FileNotFoundError('Set ARM_GCC_BIN to the ARM GNU toolchain bin directory, or put arm-none-eabi-gcc on PATH')
    return folder


def dfu_util():
    configured = os.environ.get('DFU_UTIL')
    found = shutil.which('dfu-util')
    legacy = '/Users/liu/Documents/Codex/2026-09-10/new-chat/tools/oss-cad-suite/bin/dfu-util'
    executable = str(Path(configured).expanduser()) if configured else legacy if Path(legacy).is_file() else found or legacy
    if not Path(executable).is_file():
        raise FileNotFoundError('Set DFU_UTIL to dfu-util, or put dfu-util on PATH')
    return executable

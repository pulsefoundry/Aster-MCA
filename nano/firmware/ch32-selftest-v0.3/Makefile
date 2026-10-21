TOOLCHAIN ?= riscv-none-elf-
CC = $(TOOLCHAIN)gcc
OBJCOPY = $(TOOLCHAIN)objcopy
SIZE = $(TOOLCHAIN)size
CFLAGS = -march=rv32imac_zicsr_zifencei -mabi=ilp32 -Os -g -ffunction-sections -fdata-sections -fno-common -Wall -Wextra -Isrc -Ivendor
LDFLAGS = -nostartfiles --specs=nano.specs --specs=nosys.specs -Wl,--gc-sections,-Map=build/selftest.map -Tsrc/Link.ld
SOURCES = src/main.c src/startup.S vendor/system_ch32x035.c vendor/ch32x035_rcc.c vendor/ch32x035_gpio.c vendor/ch32x035_adc.c vendor/ch32x035_dma.c vendor/ch32x035_opa.c vendor/ch32x035_usbfs_device.c vendor/usb_desc.c

.PHONY: all clean
all: build/selftest.bin build/selftest.hex

build/selftest.elf: $(SOURCES) $(wildcard src/*.h vendor/*.h) src/Link.ld
	mkdir -p build
	$(CC) $(CFLAGS) $(SOURCES) $(LDFLAGS) -o $@
	$(SIZE) $@

build/selftest.bin: build/selftest.elf
	$(OBJCOPY) -O binary $< $@

build/selftest.hex: build/selftest.elf
	$(OBJCOPY) -O ihex $< $@

clean:
	rm -rf build

TOOLBIN ?=
YOSYS ?= yosys
NEXTPNR ?= nextpnr-himbaechel
PACK ?= gowin_pack
LOADER ?= openFPGALoader
PYTHON ?= /usr/bin/python3
IVERILOG ?= iverilog
VVP ?= vvp

ifneq ($(strip $(TOOLBIN)),)
YOSYS := $(TOOLBIN)/yosys
NEXTPNR := $(TOOLBIN)/nextpnr-himbaechel
PACK := $(TOOLBIN)/gowin_pack
IVERILOG := $(TOOLBIN)/iverilog
VVP := $(TOOLBIN)/vvp
endif

DEVICE := GW1N-LV4QN88C6/I5
FAMILY := GW1N-4
TOP := top
BUILD := build
SOURCES := top.v mca_engine.v histogram.v uart_rx.v uart_tx.v
PATCHER := tools/patch_gowin_id_crc.py

.PHONY: all clean sim sim-core sim-protocol host-test detect load-sram load-adc-pulldown load-adc-pd-high

all: $(BUILD)/aster-mca-v1.fs

$(BUILD):
	mkdir -p $@

$(BUILD)/synth.json: $(SOURCES) | $(BUILD)
	$(YOSYS) -p "read_verilog $(SOURCES); synth_gowin -top $(TOP) -json $@"

$(BUILD)/pnr.json: $(BUILD)/synth.json aster-mca.cst
	$(NEXTPNR) --json $< --write $@ --device $(DEVICE) \
		--vopt family=$(FAMILY) --vopt cst=aster-mca.cst \
		--freq 10 --report $(BUILD)/timing.json

$(BUILD)/aster-mca-v1-raw.fs: $(BUILD)/pnr.json
	$(PACK) -d $(FAMILY) -o $@ $<

$(BUILD)/aster-mca-v1.fs: $(BUILD)/aster-mca-v1-raw.fs $(PATCHER)
	$(PYTHON) $(PATCHER) $< $@

# Diagnostic build: weak pull-downs distinguish an actively driven 0xfff from
# a tri-stated ADC bus.  It is SRAM-only and is not the production image.
$(BUILD)/pnr-adc-pulldown.json: $(BUILD)/synth.json aster-mca-adc-pulldown.cst
	$(NEXTPNR) --json $< --write $@ --device $(DEVICE) \
		--vopt family=$(FAMILY) --vopt cst=aster-mca-adc-pulldown.cst \
		--freq 10 --report $(BUILD)/timing-adc-pulldown.json

$(BUILD)/aster-mca-adc-pulldown-raw.fs: $(BUILD)/pnr-adc-pulldown.json
	$(PACK) -d $(FAMILY) -o $@ $<

$(BUILD)/aster-mca-adc-pulldown.fs: $(BUILD)/aster-mca-adc-pulldown-raw.fs $(PATCHER)
	$(PYTHON) $(PATCHER) $< $@

$(BUILD)/synth-adc-pd-high.json: $(SOURCES) top_adc_pd_high.v | $(BUILD)
	$(YOSYS) -p "read_verilog $(SOURCES) top_adc_pd_high.v; synth_gowin -top top_adc_pd_high -json $@"

$(BUILD)/pnr-adc-pd-high.json: $(BUILD)/synth-adc-pd-high.json aster-mca-adc-pulldown.cst
	$(NEXTPNR) --json $< --write $@ --device $(DEVICE) \
		--vopt family=$(FAMILY) --vopt cst=aster-mca-adc-pulldown.cst \
		--freq 10 --report $(BUILD)/timing-adc-pd-high.json

$(BUILD)/aster-mca-adc-pd-high-raw.fs: $(BUILD)/pnr-adc-pd-high.json
	$(PACK) -d $(FAMILY) -o $@ $<

$(BUILD)/aster-mca-adc-pd-high.fs: $(BUILD)/aster-mca-adc-pd-high-raw.fs $(PATCHER)
	$(PYTHON) $(PATCHER) $< $@

sim: sim-core sim-protocol

sim-core: $(BUILD)/tb_mca.vvp
	$(VVP) $<

sim-protocol: $(BUILD)/tb_protocol.vvp
	$(VVP) $<

host-test:
	$(PYTHON) -m unittest -v test_astermca.py

$(BUILD)/tb_mca.vvp: tb_mca.v $(SOURCES) | $(BUILD)
	$(IVERILOG) -g2012 -s tb_mca -o $@ tb_mca.v $(SOURCES)

$(BUILD)/tb_protocol.vvp: tb_protocol.v $(SOURCES) | $(BUILD)
	$(IVERILOG) -g2012 -s tb_protocol -o $@ tb_protocol.v $(SOURCES)

detect:
	$(LOADER) -c ch347_jtag --freq 1000000 --detect

# SRAM only. The image disappears when board power is removed.
load-sram: $(BUILD)/aster-mca-v1.fs
	$(LOADER) -c ch347_jtag --freq 1000000 -m $<

load-adc-pulldown: $(BUILD)/aster-mca-adc-pulldown.fs
	$(LOADER) -c ch347_jtag --freq 1000000 -m $<

load-adc-pd-high: $(BUILD)/aster-mca-adc-pd-high.fs
	$(LOADER) -c ch347_jtag --freq 1000000 -m $<

clean:
	rm -rf $(BUILD)

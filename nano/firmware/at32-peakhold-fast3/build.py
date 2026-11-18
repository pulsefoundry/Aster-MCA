from pathlib import Path
import hashlib, json, subprocess, sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tool_paths import arm_toolchain

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
SDK=ROOT/'work/at32-bringup-2026-10-14/sdk'
BUILD=HERE/'build'
BUILD.mkdir(exist_ok=True)
TOOL=arm_toolchain()
example=SDK/'project/at_start_f423/examples/usb_device/vcp_loopback'
device=SDK/'libraries/cmsis/cm4/device_support'
core=SDK/'libraries/cmsis/cm4/core_support'
drivers=SDK/'libraries/drivers'
usb=SDK/'middlewares/usb_drivers'
cdc=SDK/'middlewares/usbd_class/cdc'
for filename in ['at32f423_conf.h','usb_conf.h']:
    text=(example/'inc'/filename).read_text()
    # CDC is a command interface, not a bridge to the example board USART.
    text=text.replace('#define USB_VIRTUAL_COMPORT','/* No hardware USART bridge. */')
    (BUILD/filename).write_text(text)
for filename in ['cdc_desc.c','cdc_desc.h']:
    text=(cdc/filename).read_text()
    text=text.replace('"AT32 Virtual Com Port  "','"Aster MCA Nano AT32"')
    text=text.replace('0xC0,                                  /* bmAttributes: self powered */',
                      '0x80,                                  /* bmAttributes: USB bus powered */')
    (BUILD/filename).write_text(text)
link=(device/'startup/gcc/linker/AT32F423xC_FLASH.ld').read_text()
start=link.index('  /DISCARD/')
end=link.index('  .ARM.attributes',start)
link=link[:start]+link[end:]
link=link.replace('_Min_Stack_Size = 0x400','_Min_Stack_Size = 0x1000')
link=link.replace('    *(.data*)','    *(.data*)\n    *(.ramfunc*)')
(BUILD/'flash.ld').write_text(link)
sources=[HERE/'main.c',device/'system_at32f423.c',device/'startup/gcc/startup_at32f423.s',
         BUILD/'cdc_desc.c',cdc/'cdc_class.c']
sources += [drivers/'src'/f'at32f423_{name}.c' for name in ['crm','gpio','misc','acc','adc','flash','pwc','usb','tmr','dac','dma']]
sources += [usb/'src'/f'{name}.c' for name in ['usb_core','usbd_core','usbd_int','usbd_sdr']]
flags=['-mcpu=cortex-m4','-mthumb','-mfpu=fpv4-sp-d16','-mfloat-abi=hard','-O2','-g3',
       '-ffunction-sections','-fdata-sections','-fno-common','-DAT32F423CCT7','-DUSE_STDPERIPH_DRIVER',
       '-Wall','-Wextra','-Wno-unused-parameter']
for path in [BUILD,device,core,drivers/'inc',usb/'inc',cdc]: flags+=['-I',str(path)]
objects=[]
for i,source in enumerate(sources):
    obj=BUILD/f'{i:02d}_{source.stem}.o'
    subprocess.run([str(TOOL/'arm-none-eabi-gcc'),*flags,'-c',str(source),'-o',str(obj)],check=True)
    objects.append(str(obj))
elf=BUILD/'aster-at32-peakhold-fast-3.elf'
subprocess.run([str(TOOL/'arm-none-eabi-gcc'),*flags,*objects,'-nostartfiles','--specs=nano.specs',
               '--specs=nosys.specs','-T',str(BUILD/'flash.ld'),'-Wl,--gc-sections',
               f'-Wl,-Map={BUILD}/firmware.map','-o',str(elf)],check=True)
binary=elf.with_suffix('.bin')
subprocess.run([str(TOOL/'arm-none-eabi-objcopy'),'-O','binary',str(elf),str(binary)],check=True)
subprocess.run([str(TOOL/'arm-none-eabi-size'),str(elf)],check=True)
b=binary.read_bytes()
assert len(b)<256*1024
sp=int.from_bytes(b[:4],'little'); reset=int.from_bytes(b[4:8],'little')
assert 0x20000000<sp<=0x2000c000 and 0x08000000<reset<0x08000000+len(b) and reset&1
manifest={'firmware':'0.4.1-fast.3', 'board':'AT32 v0.4.1 PTH + peak-hold carrier', 'purpose':'144MHz, 4MSa/s RAW pretrigger DMA, fast held peak readout','mcu':'AT32F423CCT7','flash_start':'0x08000000','flash_bytes':262144,
          'erase_page_bytes':2048,'binary_bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),
          'sdk_commit':'a60472b248c39034f111ac17e7b1286549594435','stack':hex(sp),'reset_vector':hex(reset)}
symbols={line.split()[-1]:int(line.split()[0],16) for line in subprocess.check_output(
    [str(TOOL/'arm-none-eabi-nm'),'-n',str(elf)],text=True).splitlines() if len(line.split())==3}
assert symbols['_ebss']+4096<=sp, 'Insufficient stack margin'
hot={k:symbols[k] for k in ['TMR3_GLOBAL_IRQHandler','DMA1_Channel1_IRQHandler']}
assert all(symbols['_sdata']<=v<symbols['_edata'] for v in hot.values()), 'Fast IRQ not copied to SRAM'
manifest.update(core_hz=144000000,adc_hz=72000000,raw_sample_rate_hz=4000000,
                raw_timer_ticks=36,ldo_mv=1300,raw_ring_samples=256,
                ram_static_bytes=symbols['_ebss']-0x20000000,
                stack_margin_bytes=sp-symbols['_ebss'],
                hot_functions={k:hex(v) for k,v in hot.items()})
manifest.update(default_stop_phase='hold',
                adc_profiles_mhz=[72,36,24,12],raw_profile_rates_hz=[4000000,2000000,1000000,500000],
                peak_sample_cycles_x2=[49,95,185,495],
                dma_stop_timing_reference='TMR3_C2_IRQ_entry; signed cycles')
(BUILD/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest))

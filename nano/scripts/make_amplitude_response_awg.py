"""Prepare a native OWON file for amplitude-response diagnosis, entirely offline.

Keeps the exact point payload of the previously imported N61116A waveform.
Physical voltage/frequency settings are a separate plan, not stored in the BIN.
"""
from pathlib import Path
import datetime
import hashlib
import json
import math
import shutil
import struct

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/Aster-MCA-Nano-幅度响应测试波形-20261118'
NAME='N61118A.bin'
N=8192
DT_US=.125
START_US=128.
WIDTH_US=4.
FREQUENCY_HZ=1e6/(N*DT_US)


def main():
    OUT.mkdir(exist_ok=False)
    intended=[];codes=[]
    for index in range(N):
        elapsed=index*DT_US-START_US
        envelope=math.sin(math.pi*elapsed/WIDTH_US)**2 if 0<elapsed<WIDTH_US else 0.
        intended.append(-envelope)
        codes.append(round(20000*(1-envelope)))
    native=(struct.pack('<4i',1,20000,0,N)+NAME.encode('ascii').ljust(32,b'\0')+
            struct.pack('<'+'H'*N,*codes))
    old=ROOT/'outputs/Aster-MCA-Nano-峰值保持测试波形-20261116/N61116A.bin'
    old_bytes=old.read_bytes()
    assert hashlib.sha256(old_bytes).hexdigest()=='26820fc28a9f78ff3b441382f49be60c7e1ef9a45a6a3be627ef39f98d2cc9c2'
    assert native[:16]==old_bytes[:16] and native[48:]==old_bytes[48:]
    assert len(native)==16432 and min(codes)==0 and max(codes)==20000
    (OUT/NAME).write_bytes(native)
    # Decode the saved bytes, independently of the writer's code list.
    decoded=(OUT/NAME).read_bytes()
    assert struct.unpack_from('<4i',decoded)==(1,20000,0,N)
    assert decoded[16:48].split(b'\0')[0].decode('ascii')==NAME
    samples=struct.unpack_from('<'+'H'*N,decoded,48)
    nonbaseline=[i for i,v in enumerate(samples) if v!=20000]
    assert nonbaseline==list(range(1025,1056))
    assert samples[1024]==samples[1056]==20000 and samples[1040]==0
    assert all(samples[1040-i]==samples[1040+i] for i in range(17))
    reconstructed=[q/20000-1 for q in samples]
    error=max(abs(a-b) for a,b in zip(intended,reconstructed))
    assert error<=1/40000+1e-12
    scan=[100,150,200,250,300,400,500,750,1000,1250,1500,1750]
    plan=dict(file=NAME,generated_at=datetime.datetime.now().astimezone().isoformat(),format='OWON Ultrawave native;4LEint32+32byte filename+8192LEuint16',
        bytes=len(native),sha256=hashlib.sha256(native).hexdigest(),
        payload_sha256=hashlib.sha256(native[48:]).hexdigest(),points=N,
        shape='Single negative sin-squared pulse from nominal zero baseline',
        point_time_us_at_target_frequency=DT_US,period_us=N*DT_US,
        pulse_start_us=START_US,pulse_end_us=START_US+WIDTH_US,
        total_pulse_width_us=WIDTH_US,pulse_fwhm_us=2.,
        first_edge_to_peak_us=2.,peak_to_baseline_us=2.,
        target_frequency_hz=FREQUENCY_HZ,
        initial_instrument_settings=dict(amplitude_vpp=.5,offset_v=-.25,
            load='High Z',nominal_baseline_v=0.,nominal_negative_peak_v=-.5,
            frequency_hz=FREQUENCY_HZ,output_enable=False),
        amplitude_scan=[dict(amplitude_mvpp=a,offset_mv=-a/2,nominal_baseline_mv=0,
                             nominal_negative_peak_mv=-a) for a in scan],
        amplitude_and_frequency_embedded_in_bin=False,
        instrument_connection_attempted=False,instrument_uploaded=False,analog_output_measured=False,
        previous_format_evidence=dict(file=str(old),same_payload=True,
            previous_readback_verified=True,previously_reported_model='AG1022',
            evidence='work/owon-awg-20261116/upload-first.json'),
        validation=dict(header_roundtrip=True,sample_payload_roundtrip=True,
            symmetry=True,single_pulse=True,matching_previous_verified_payload=True,
            maximum_normalized_geometry_error=error),
        scope='Offline generation only. No USB/network device commands and no Nano operation.')
    (OUT/'waveform-settings.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
    lines=['Aster MCA Nano：幅度响应测试波形，2026-11-18','',
        '主文件：N61118A.bin；保持名称，按上次USB上传/前面板调出流程加载。',
        '本次仅生成离线文件，没有连接、上传或操作发生器/Nano。',
        '文件格式和点表与上次成功导入的N61116A.bin相同，仅内嵌文件名更新。',
        '本次新文件还没有上机读回或实测模拟输出。','',
        '波形：平直零基线上的单个向下sin²圆顶脉冲。',
        '按目标频率播放时：总宽4us（包含下行及返回），FWHM2us，下行到峰2us、返回2us。',
        '8192点/周期；周期1.024ms；目标频率976.5625Hz（显示可约为976.56Hz）。',
        '4us脉冲跨32个点间隔。点表等效步进0.125us，不等同于仪器DAC时钟。',
        '单独改变播放频率会同比改变脉宽；本次幅度扫描保持频率和波形不变。','',
        '建议首次上机设置（尚未执行）：',
        '模式：ARB / N61118A.bin',
        '幅度：500mVpp',
        '直流偏置：-250mV',
        '负载显示：High Z',
        '高/低电平名义值：0V / -500mV',
        '频率：976.5625Hz',
        '输出：OFF，核对设置后再进行接线与启用。','',
        '文件只存归一化形状，不包含最终电压和频率设置。',
        '重要的实机记录：上次这台发生器调出文件后曾恢复到20Vpp、0V偏置。',
        '因此每次调出均先关闭输出，随后重新设置并核对幅度、偏置、频率和High Z，再接Nano。','',
        '幅度扫描计划（同一个BIN即可，无需每档换文件）：',
        '幅度mVpp    偏置mV    名义负峰mV']
    lines += [f'{a:>8}    {-a/2:>7g}    {-a:>10g}' for a in scan]
    lines += ['',
        '低幅度档可能不触发，要记录为结果。先确认通路，再按固定档位扫描，不为了补低点而中途改变门限或形状。',
        '每档输出应按High Z设置核对实际幅度；这些名义值不是本次示波器实测值。',
        '目标是检查输入幅度与PEAK道数的线性/零偏，同时记录可见的低幅度响应。',
        '周期发生器与Nano的复位/等待门存在相位和死时间影响；收到事件数不能直接除以发生器频率称作绝对触发效率。',
        'waveform-preview.png按建议500mVpp/-250mV绘制，仅为目标波形预览。',
        'waveform-settings.json记录格式、参数、扫描点和完整校验信息。']
    (OUT/'使用说明.txt').write_text('\n'.join(lines)+'\n')
    shutil.copy2(Path(__file__),OUT/'make_amplitude_response_awg.py')
    print(json.dumps({'output':str(OUT),'file':str(OUT/NAME),'bytes':len(native),
        'same_point_payload_as_previous':True,'normalized_quantization_error':error},ensure_ascii=False))


if __name__=='__main__':main()

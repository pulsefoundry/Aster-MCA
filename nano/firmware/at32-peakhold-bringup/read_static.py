"""Read three idle ADC channels; verify every raw frame using host arithmetic."""
from pathlib import Path
import argparse
import datetime
import glob
import importlib.util
import json
import os
import time

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('baseline_transport', HERE.parent / 'at32-bringup/read_baseline.py')
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    ports = glob.glob('/dev/cu.usbmodem*')
    assert len(ports) == 1, 'Expected exactly one USB CDC serial port'
    args.output.mkdir(parents=True, exist_ok=False)
    result = {'completed': False, 'port': ports[0], 'mode': 'idle_reset',
              'input_condition': 'SMA disconnected as requested; user reported BOOT reinsertion',
              'started': datetime.datetime.now().astimezone().isoformat(), 'captures': []}
    serial = None
    try:
        serial = transport.Serial(ports[0])

        def info(command='INFO'):
            v = json.loads(serial.command(command))
            assert v['board'] == 'Aster MCA Nano AT32 v0.4.1 PTH'
            assert v['fw'] == '0.4.1-bringup.1' and v['mode'] == 'idle_reset'
            assert v['hold'] == 1 and v['peak_reset'] == 1
            assert v['adc_fault'] == 0
            return v

        result['initial_info'] = info()
        assert serial.command('PING') == 'PONG'
        for channel in ['PEAK', 'RAW', 'BASE']:
            v = info('CHANNEL ' + channel)
            assert v['channel'] == channel
            for i in range(3):
                stats = transport.capture(serial, args.output / f'{channel.lower()}-{i+1:02d}')
                assert stats['channel'] == channel
                result['captures'].append(stats)
                print(channel, 'mean', round(stats['mean_code'], 3),
                      'RMS', round(stats['rms_code'], 3),
                      'range', stats['min'], stats['max'], 'CRC OK', flush=True)
        result['adc_off_info'] = info('ADC OFF')
        assert result['adc_off_info']['adc_on'] == 0
        assert serial.command('STATS') == 'ERR ADC_DISABLED_OR_FAULT'
        json.loads(serial.line())
        result['adc_on_info'] = info('ADC ON')
        assert result['adc_on_info']['adc_on'] == 1
        info('CHANNEL PEAK')
        time.sleep(1.1)
        result['final_info'] = info()
        assert result['final_info']['led_edges'] > result['initial_info']['led_edges']
        result['completed'] = True
    except Exception as exc:
        result['error'] = repr(exc)
        raise
    finally:
        if serial is not None:
            os.close(serial.fd)
        (args.output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print('OUTPUT', args.output, flush=True)


if __name__ == '__main__':
    main()

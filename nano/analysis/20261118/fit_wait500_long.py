"""Strict fast.7/500us replay with the established peak and minute-drift fitter.

Offline only. Native data stay unchanged. A conservative analog-range selection
is applied to the analysis copy, with every additional exclusion recorded.
"""
from pathlib import Path
import argparse
import copy
import hashlib
import importlib.util
import json
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'firmware/at32-peakhold-fast7'))
from capture_spectrum import decode_batch,FW
BASE=HERE/'fit_long_run.py'
spec=importlib.util.spec_from_file_location('established_long_fitter',BASE)
analysis=importlib.util.module_from_spec(spec);spec.loader.exec_module(analysis)
analysis.decode_batch=lambda head,raw:decode_batch(head,raw,wait_limit_us=500)
original_load=analysis.load_run


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('run',type=Path);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();args.out.mkdir(exist_ok=False)
    source=json.loads((args.run/'spectrum.json').read_text())
    assert source['completed'] and source['wait_limit_us']==500 and FW=='0.4.1-fast.7'
    logs=[json.loads(line) for line in (args.run/'batches.jsonl').read_text().splitlines()]
    for key,value in source['internal_timing_sums'].items():
        assert sum(b['header'][key] for b in logs)==value,key

    def guarded_load(run,allow_incomplete=False):
        data,hists,selected,quality=original_load(run,allow_incomplete)
        assert len(quality['analog_high_records'])==quality['records_above_nominal_1p65v'], 'Truncated high-record list'
        data=copy.deepcopy(data)
        durations=analysis.np.array([b['host_roundtrip_seconds'] for b in logs])
        ends=analysis.np.cumsum(durations)*data['wall_seconds']/durations.sum()
        starts=analysis.np.r_[0,ends[:-1]]
        mapping={b['file']:min(len(hists)-1,int((start+end)/2//60))
                 for b,start,end in zip(logs,starts,ends)}
        extra=0
        for row in quality['analog_high_records']:
            channel=row['amplitude_channel']
            if row['flags'] or row['peak_code']>=4090 or not 0<=channel<2048:continue
            bin_index=int(channel);segment=mapping[row['file']]
            data['counts'][bin_index]-=1;hists[segment,bin_index]-=1;selected[segment]-=1
            extra+=1
        assert min(data['counts'])>=0 and analysis.np.all(hists>=0)
        assert analysis.np.array_equal(hists.sum(axis=0),data['counts'])
        data['totals']['binned']-=extra
        quality.update(original_base_selected=quality['selected'],additionally_excluded_analog_high=extra,
                       selected=sum(data['counts']),all_internal_timing_sums_verified=True,
                       baseline_summary_selection='Baseline diagnostics retain the original base quality selection; peak/count histograms apply the extra analog guard.')
        assert sum(data['counts'])==data['totals']['binned']
        (args.out/'valid-range-spectrum.json').write_text(json.dumps(dict(
            counts=data['counts'],bins=2048,adc_codes_per_channel=2,selected=sum(data['counts']),
            additionally_excluded_analog_high=extra,energy_calibrated=False,
            selection='Existing no-flag/no-clipping selection plus max(PEAK1..4)<2048; nominal3.3V reference.'),indent=2)+'\n')
        return data,hists,selected,quality

    analysis.load_run=guarded_load
    # Fit-window/model sensitivity is retained. No redundant conditional model
    # bootstrap is run; it would not account for the observed model mismatch.
    sys.argv=['established_long_fitter',str(args.run),'--out',str(args.out),'--bootstrap','0']
    analysis.main()
    path=args.out/'analysis.json';report=json.loads(path.read_text())
    report.update(firmware=FW,wait_limit_us=500,original_capture_totals=source['totals'],
                  internal_timing_sums=source['internal_timing_sums'],
                  armed_observed_seconds=source['internal_timing_sums']['armed_observed_cycles']/144000000,
                  source_fitter_sha256=hashlib.sha256(BASE.read_bytes()).hexdigest(),
                  wrapper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    report['limitations'].append('Additional analog guard is applied only to the analysis copy; native spectrum/frames unchanged. Armed-observed seconds include capture/IRQ latency and are not true live time.')
    path.write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()

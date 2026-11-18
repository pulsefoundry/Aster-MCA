#!/usr/bin/env python3
"""Independent EPRO record readback: pin nets, pad geometry and dimensions.

This does not replace the editor's schematic synchronization and native DRC.
"""
from pathlib import Path
import argparse, json, math
import native_base as n

def audit(folder):
    d=json.loads((folder/'design-manifest.json').read_text());g=json.loads((folder/'component-geometry.json').read_text());docs=n.parse_archive(folder/(d['name']+'.epro2'))
    byid={x['head']['uuid']:x for x in docs};pcb=next(x for x in docs if x['head']['docType']=='PCB')
    attrs={};instances={};padnets={}
    for h,a in pcb['r']:
        if h['type']=='COMPONENT':instances[h['id']]=a
        elif h['type']=='ATTR':attrs.setdefault(a['parentId'],{})[a['key']]=a['value']
        elif h['type']=='PAD_NET':key=json.loads(h['id']);padnets[key[1],key[3]]=a['padNet'] or None
    expected={(p['ref'],num):net for p in d['parts'] for num,net in p['nets'].items()}
    native={};geom={};errors=[]
    for ident,inst in instances.items():
        at=attrs[ident];ref=at['Designator'];fp=byid[at['Footprint']];theta=math.radians(inst.get('angle',0));co,si=math.cos(theta),math.sin(theta)
        for h,a in fp['r']:
            if h['type']!='PAD' or not a['num']:continue
            key=ref,a['num'];net=padnets.get((ident,h['id']))
            if key in native and native[key]!=net:errors.append('duplicate pad net mismatch: '+str(key))
            native[key]=net
            x=(inst['x']+a['centerX']*co-a['centerY']*si)*.0254
            y=-(inst['y']+a['centerX']*si+a['centerY']*co)*.0254
            geom.setdefault(key,[]).append([x,y,a['defaultPad']['width']*.0254,a['defaultPad']['height']*.0254,a['hole']['width']*.0254,a['hole']['height']*.0254])
    for key in set(expected)|set(native):
        if expected.get(key)!=native.get(key) or (key in expected)!=(key in native):errors.append('net mismatch '+str(key))
    max_geometry_error=0
    for fp in g:
        for pad in fp['pads']:
            if not pad['num']:continue
            key=fp['ref'],pad['num'];target=pad['xy']+pad['size']+sorted(pad['drill'],reverse=True)
            if key not in geom:errors.append('missing pad '+str(key));continue
            distance=min(max(abs(a-b) for a,b in zip(row,target)) for row in geom[key]);max_geometry_error=max(max_geometry_error,distance)
            if distance>1e-5:errors.append('geometry mismatch '+str(key)+' '+str(distance))
    # All symbol pin numbers have a correspondingly numbered footprint pad.
    devices=[x for x in docs if x['head']['docType']=='DEVICE'];device_count=0
    for device in devices:
        meta=next(a for h,a in device['r'] if h['type']=='META');at=meta['attributes']
        if not at.get('Footprint'):continue
        device_count+=1;symbol=byid[at['Symbol']];fp=byid[at['Footprint']]
        pins={a['value'] for h,a in symbol['r'] if h['type']=='ATTR' and a.get('key')=='Pin Number'}
        pads={a['num'] for h,a in fp['r'] if h['type']=='PAD' and a['num']}
        if pins!=pads:errors.append('symbol/footprint mismatch '+meta['title'])
    result={'status':'PASS' if not errors else 'FAIL','checks':['Expected nets versus native PCB PAD_NET','Native physical pad coordinates versus KiCad readback','All symbol pin numbers mapped to footprint pad numbers'],'components':len(d['parts']),'devices':device_count,'pins':len(expected),'maximum_geometry_error_mm':max_geometry_error,'errors':errors,'native_editor_drc':'NOT_PERFORMED_BY_THIS_SCRIPT','fabrication_release':False}
    (folder/'structural-audit.json').write_text(json.dumps(result,indent=2));return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path);args=parser.parse_args();report=audit(args.folder);print(json.dumps(report,indent=2));raise SystemExit(bool(report['errors']))

#!/usr/bin/env python3
"""Compare native track/via/outline records against routed KiCad PCB."""
from pathlib import Path
import sys,json,math,collections
import wx
app=wx.App(False)
import pcbnew as k
import native_base as n
folder=Path(sys.argv[1]);d=json.loads((folder/'design-manifest.json').read_text());b=k.LoadBoard(str(folder/(d['name']+'.kicad_pcb')));docs=n.parse_archive(folder/(d['name']+'.epro2'));pcb=next(x for x in docs if x['head']['docType']=='PCB')
def mm(p):return [k.ToMM(p.x),k.ToMM(p.y)]
def q(vals):return tuple(round(x,5) if isinstance(x,(float,int)) else x for x in vals)
kn=[];nn=[]
for t in b.GetTracks():
 if isinstance(t,k.PCB_VIA):kn.append(q(['via',t.GetNetname()]+mm(t.GetPosition())+[k.ToMM(t.GetDrill()),k.ToMM(t.GetWidth(k.F_Cu))]))
 else:
  a,z=sorted([mm(t.GetStart()),mm(t.GetEnd())]);kn.append(q(['line',t.GetNetname(),1 if t.GetLayer()==k.F_Cu else 2]+a+z+[k.ToMM(t.GetWidth())]))
for h,a in pcb['r']:
 if h['type']=='VIA':nn.append(q(['via',a['netName'],a['centerX']*.0254,-a['centerY']*.0254,a['holeDiameter']*.0254,a['viaDiameter']*.0254]))
 elif h['type']=='LINE':
  s,e=sorted([[a['startX']*.0254,-a['startY']*.0254],[a['endX']*.0254,-a['endY']*.0254]]);nn.append(q(['line',a['netName'],a['layerId']]+s+e+[a['width']*.0254]))
missing=list((collections.Counter(kn)-collections.Counter(nn)).elements());extra=list((collections.Counter(nn)-collections.Counter(kn)).elements())
halfholes=[]
for f in b.GetFootprints():
 for p in f.Pads():
  x,y=mm(p.GetPosition());w,h=d['size_mm']
  if p.GetAttribute()!=k.PAD_ATTRIB_PTH or min(abs(x),abs(y),abs(x-w),abs(y-h))>.00001:continue
  halfholes.append({'reference':f.GetReference(),'number':p.GetNumber(),'xy_mm':mm(p.GetPosition()),'drill_mm':mm(p.GetDrillSize()),'size_mm':mm(p.GetSize()),'plated':True,'on_both_copper_layers':p.IsOnLayer(k.F_Cu) and p.IsOnLayer(k.B_Cu),'paste':p.IsOnLayer(k.F_Paste) or p.IsOnLayer(k.B_Paste)})
usb={}
for net in ['USB_DP','USB_DM','USB_DP_CONN','USB_DM_CONN','MCU_USB_DP','MCU_USB_DM']:
 tracks=[t for t in b.GetTracks() if t.GetNetname()==net];usb[net]={'length_mm':sum(k.ToMM(t.GetLength()) for t in tracks if not isinstance(t,k.PCB_VIA)),'vias':sum(isinstance(t,k.PCB_VIA) for t in tracks)}
report={'copper_records_match':not missing and not extra,'missing':missing,'extra':extra,'copper_layers':b.GetCopperLayerCount(),'tracks_and_vias':len(kn),'halfholes':halfholes,'usb_routes':usb,'usb_impedance_or_signal_integrity_validated':False,'native_editor_DRC':'separate gate'}
(folder/'copper-audit.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='halfholes'},indent=2))
assert not missing and not extra

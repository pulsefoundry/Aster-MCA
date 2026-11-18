#!/usr/bin/env python3
"""Generate a placement preview from actual KiCad PCB pad and track geometry."""
from pathlib import Path
import argparse,html,json,math
import wx
_app=wx.App(False)
import pcbnew as k

def xy(p):return k.ToMM(p.x),k.ToMM(p.y)
def run(folder):
 d=json.loads((folder/'design-manifest.json').read_text());b=k.LoadBoard(str(folder/(d['name']+'.kicad_pcb')));w,h=d['size_mm']
 for bottom in (False,True):
  layer=k.B_Cu if bottom else k.F_Cu
  s=[f'<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="{int(1100*(h+5)/(w+4))}" viewBox="-2 -2 {w+4} {h+5}">',f'<rect x="-2" y="-2" width="{w+4}" height="{h+5}" fill="#f1f4f7"/>',f'<rect width="{w}" height="{h}" fill="#174b3b" stroke="#172c27" stroke-width=".15"/>']
  if bottom:s.append(f'<g transform="translate({w} 0) scale(-1 1)">')
  for t in b.GetTracks():
   if isinstance(t,k.PCB_VIA):
    x,y=xy(t.GetPosition());s.append(f'<circle cx="{x}" cy="{y}" r="{k.ToMM(t.GetWidth(layer))/2}" fill="#c9a754"/>');s.append(f'<circle cx="{x}" cy="{y}" r="{k.ToMM(t.GetDrill())/2}" fill="#152d26"/>')
   elif t.GetLayer()==layer:
    x,y=xy(t.GetStart());xx,yy=xy(t.GetEnd());s.append(f'<path d="M{x},{y} L{xx},{yy}" stroke="{"#d5835c" if not bottom else "#66a9d1"}" stroke-width="{k.ToMM(t.GetWidth())}" fill="none" stroke-linecap="round"/>')
  for f in b.GetFootprints():
   for pad in f.Pads():
    if not pad.IsOnLayer(layer):continue
    x,y=xy(pad.GetPosition());pw,ph=xy(pad.GetSize());dw,dh=xy(pad.GetDrillSize());a=-pad.GetOrientationDegrees();r=min(pw,ph)*(.5 if pad.GetShape() in (k.PAD_SHAPE_CIRCLE,k.PAD_SHAPE_OVAL) else .1)
    s.append(f'<g transform="translate({x} {y}) rotate({a})"><rect x="{-pw/2}" y="{-ph/2}" width="{pw}" height="{ph}" rx="{r}" fill="#dab85f" stroke="#fcdfa0" stroke-width=".035"/>')
    if dw:s.append(f'<rect x="{-dw/2}" y="{-dh/2}" width="{dw}" height="{dh}" rx="{min(dw,dh)/2}" fill="#f1f4f7"/>')
    s.append('</g>')
   if not bottom:
    for g in f.GraphicalItems():
     if isinstance(g,k.PCB_SHAPE) and g.GetLayer()==k.F_Fab and g.GetShape()==k.SHAPE_T_SEGMENT:
      x,y=xy(g.GetStart());xx,yy=xy(g.GetEnd());s.append(f'<path d="M{x},{y} L{xx},{yy}" stroke="#d9e6dd" stroke-width=".06" fill="none"/>')
    if f.GetReference()!='J1':
     x,y=xy(f.GetPosition());s.append(f'<text x="{x}" y="{y}" fill="white" font-family="sans-serif" font-size=".65" text-anchor="middle">{html.escape(f.GetReference())}</text>')
  if bottom:s.append('</g>')
  s.append(f'<text x="0" y="{h+1.6}" fill="#1d2833" font-family="sans-serif" font-size=".65">{"BOTTOM" if bottom else "TOP"} · {w} × {h} mm · DRAFT / NOT FOR FABRICATION</text></svg>')
  (folder/('pcb-bottom.svg' if bottom else 'pcb-top.svg')).write_text('\n'.join(s))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('folder',type=Path);run(p.parse_args().folder)

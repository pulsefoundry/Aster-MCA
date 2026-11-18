#!/usr/bin/env python3
"""Read-only manufacturing geometry snapshot from the frozen KiCad sources."""
import json, math, sys
from pathlib import Path
import wx
app=wx.App(False)
import pcbnew as k

def mm(p): return [k.ToMM(p.x),k.ToMM(p.y)]
for name in ('core','carrier'):
    out=Path(__file__).parent/(name+'-output')
    board=k.LoadBoard(str(next(out.glob('*.kicad_pcb'))))
    drills=[]; pads=[]
    for f in board.GetFootprints():
        for p in f.Pads():
            x,y=mm(p.GetPosition()); a=math.radians(p.GetOrientationDegrees())
            dx,dy=mm(p.GetDrillSize())
            pads.append({'ref':f.GetReference(),'num':p.GetNumber(),'net':p.GetNetname(),'xy':[x,-y],
                         'size':mm(p.GetSize()),'angle':p.GetOrientationDegrees(),
                         'copper_layers':[side for side,layer in [('top',k.F_Cu),('bottom',k.B_Cu)] if p.IsOnLayer(layer)],
                         'mask_layers':[side for side,layer in [('top',k.F_Mask),('bottom',k.B_Mask)] if p.IsOnLayer(layer)]})
            if min(dx,dy)<=0: continue
            kind='NPTH' if p.GetAttribute()==k.PAD_ATTRIB_NPTH else 'PTH'
            # KiCad rotates local x toward negative board y at positive angles.
            vx,vy=((dx-dy)*math.cos(a),(dx-dy)*math.sin(a)) if dx>=dy else (-(dy-dx)*math.sin(a),(dy-dx)*math.cos(a))
            drills.append([kind,x,-y,min(dx,dy),abs(vx),abs(vy)])
    for t in board.GetTracks():
        if isinstance(t,k.PCB_VIA):
            x,y=mm(t.GetPosition());drills.append(['PTH',x,-y,k.ToMM(t.GetDrill()),0,0])
    data={'board_thickness_mm':k.ToMM(board.GetDesignSettings().GetBoardThickness()),
          'copper_layers':board.GetCopperLayerCount(),'pads':pads,'drills':drills}
    (out/'prototype-fabrication'/'expected-cam.json').write_text(json.dumps(data,indent=2))
    print(name,len(pads),'pads',len(drills),'drills')

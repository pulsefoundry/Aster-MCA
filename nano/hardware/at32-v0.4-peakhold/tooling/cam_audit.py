#!/usr/bin/env python3
"""Independent Gerber/Excellon readback, and copper-inclusive CAM previews.

This does not replace native DRC, manufacturing review, or analog validation.
"""
import json,collections,hashlib,warnings
from pathlib import Path
from gerbonara import GerberFile,ExcellonFile,LayerStack
from gerbonara.graphic_objects import Flash,Line
warnings.filterwarnings('ignore',category=SyntaxWarning)
for name,w,h in [('core',26,20),('carrier',60,32)]:
    out=Path(__file__).parent/(name+'-output');cam=out/'prototype-fabrication'
    d=json.loads((cam/'expected-cam.json').read_text())
    edges=GerberFile.open(next(cam.glob('*.gm1'))).objects
    corners=[(round(x,4),round(y,4)) for e in edges for x,y in [(e.x1,e.y1),(e.x2,e.y2)]]
    assert len(edges)==4 and set(corners)=={(0,0),(w,0),(w,-h),(0,-h)}
    assert set(collections.Counter(corners).values())=={2}
    actual=[]
    for file in cam.glob('*.drl'):
        kind='NPTH' if file.name.endswith('-NPTH.drl') else 'PTH'
        for o in ExcellonFile.open(file).objects:
            if isinstance(o,Flash):actual.append([kind,o.x,o.y,o.aperture.diameter,0,0])
            elif isinstance(o,Line):actual.append([kind,(o.x1+o.x2)/2,(o.y1+o.y2)/2,o.aperture.diameter,abs(o.x2-o.x1),abs(o.y2-o.y1)])
            else:raise AssertionError(('unhandled drill object',o))
    remaining=actual.copy()
    for ex in d['drills']:
        ix=next((i for i,ac in enumerate(remaining) if ex[0]==ac[0] and all(abs(a-b)<.002 for a,b in zip(ex[1:],ac[1:]))),None)
        assert ix is not None,('missing drill',name,ex)
        remaining.pop(ix)
    assert not remaining,('extra drills',remaining)
    checked={}
    for side,ext in [('top','gtl'),('bottom','gbl')]:
        copper=GerberFile.open(next(cam.glob('*.'+ext)))
        flashes=[o for o in copper.objects if isinstance(o,Flash)]
        expected=[p for p in d['pads'] if side in p['copper_layers'] and p['num']]
        for p in expected:
            assert any(abs(o.x-p['xy'][0])<.002 and abs(o.y-p['xy'][1])<.002 for o in flashes),('pad flash missing',name,side,p)
        checked[side]=len(expected)
    halfholes=[e for e in actual if e[0]=='PTH' and abs(e[3]-.8)<.0001 and min(abs(e[2]),abs(e[2]+h))<.0001]
    if name=='core':
        assert len(halfholes)==22
        assert {(p[1],p[2]) for p in halfholes}=={(x,y) for x in range(3,24,2) for y in [0,-20]}
    else:assert not halfholes
    stack=LayerStack.open(cam)
    for side in ['top','bottom']:
        (cam/f'CAM-{side}.svg').write_text(str(stack.to_pretty_svg(side=side,margin=1,force_bounds=((0,-h),(w,0)))))
    before=json.loads((cam/'source-hashes.json').read_text())
    assert all(hashlib.sha256((out/f).read_bytes()).hexdigest()==v for f,v in before.items())
    report={'status':'NOT_FOR_FAB','audit_scope':'Independent CAM outline/drill geometry and copper-pad center readback; no native or physical validation claim',
            'outline_mm':[w,h],'outline_closed':True,'copper_layers':d['copper_layers'],'board_thickness_mm':d['board_thickness_mm'],
            'expected_drill_count':len(d['drills']),'cam_drill_count':len(actual),'drill_geometry_matches':True,
            'pth_count':sum(x[0]=='PTH' for x in actual),'npth_count':sum(x[0]=='NPTH' for x in actual),
            'plated_slots':sum(x[0]=='PTH' and max(x[4:])>.00001 for x in actual),'halfholes':halfholes,
            'copper_pad_centers_checked':checked,'frozen_sources_unchanged':True}
    (cam/'cam-readback-audit.json').write_text(json.dumps(report,indent=2))
    print(name,json.dumps({k:v for k,v in report.items() if k!='halfholes'}))

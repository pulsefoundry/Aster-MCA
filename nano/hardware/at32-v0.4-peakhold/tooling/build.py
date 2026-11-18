#!/usr/bin/env python3
"""Build editable CAD drafts from an explicit design.json. No release certification.

Run with KiCad's Python. The EPRO output is schematic + placement/routing as
currently present. Native schematic synchronization and PCB DRC are mandatory.
"""
from pathlib import Path
import argparse, copy, csv, json, math, re, sys, uuid, zipfile
import wx
_app=wx.App(False)
import pcbnew as k
import native_base as n

CAD = Path(__file__).resolve().parent
ROOT = CAD.parents[2]
LIB = Path('/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints')
DEFAULT_TEMPLATE = ROOT/'outputs/Aster-MCA-Nano-AT32-v0.3-USB-A-LED/Aster-MCA-Nano-AT32-v0.3-USB-A-LED-EDA-VERIFIED.epro2'

def v(x,y): return k.VECTOR2I(k.FromMM(x),k.FromMM(y))
def xy(p): return [k.ToMM(p.x),k.ToMM(p.y)]
def segment(b,a,z,layer,width=.1,net=None):
    if net:
        s=k.PCB_TRACK(b);s.SetNet(b.FindNet(net))
    else:
        s=k.PCB_SHAPE();s.SetShape(k.SHAPE_T_SEGMENT)
    s.SetStart(v(*a));s.SetEnd(v(*z));s.SetWidth(k.FromMM(width));s.SetLayer(layer);b.Add(s)

def normalize(d):
    d=copy.deepcopy(d)
    d['name']=d['name'].replace('-NOT_FOR_FAB','')+'-NOT_FOR_FAB'
    assert len(d['size_mm'])==2 and min(d['size_mm'])>0
    refs=set()
    for p in d['parts']:
        assert p['ref'] not in refs,p['ref'];refs.add(p['ref'])
        p['nets']={str(key):value for key,value in p['nets'].items()}
        p['names']={str(key):str(value) for key,value in p.get('names',{}).items()}
        p.setdefault('angle',0);p.setdefault('sheet',1);p.setdefault('notes','')
        p.setdefault('kind', 'R' if p['ref'].startswith('R') else 'C' if p['ref'].startswith('C') else 'LED' if p['ref'].startswith('LED') else 'D' if p['ref'].startswith('D') else 'TP' if p['ref'].startswith('TP') else 'IC')
    d.setdefault('sheets',[{'id':i,'title':'Circuit '+str(i)} for i in sorted({p['sheet'] for p in d['parts']})])
    for i,s in enumerate(d['sheets']):
        if isinstance(s,str):d['sheets'][i]={'id':i+1,'title':s}
    assert {p['sheet'] for p in d['parts']}<={s['id'] for s in d['sheets']}
    return d

def custom_footprint(p):
    f=k.FOOTPRINT(None);f.SetFPID(k.LIB_ID('AsterCustom',p.get('fp',p['ref']).replace(':','_')))
    types={'smd':k.PAD_ATTRIB_SMD,'thru_hole':k.PAD_ATTRIB_PTH,'npth':k.PAD_ATTRIB_NPTH}
    shapes={'rect':k.PAD_SHAPE_RECT,'oval':k.PAD_SHAPE_OVAL,'circle':k.PAD_SHAPE_CIRCLE,'roundrect':k.PAD_SHAPE_ROUNDRECT}
    for a in p['custom_pads']:
        pad=k.PAD(f);pad.SetNumber(str(a['num']));pad.SetPosition(v(*a['xy']));pad.SetSize(v(*a['size']))
        typ=a.get('type','smd');pad.SetAttribute(types[typ]);pad.SetShape(shapes[a.get('shape','rect')])
        if a.get('shape')=='roundrect':pad.SetRoundRectRadiusRatio(a.get('radius_ratio',.2))
        drill=a.get('drill',0)
        if isinstance(drill,(int,float)):drill=[drill,drill]
        pad.SetDrillSize(v(*drill))
        if drill[0]!=drill[1]:pad.SetDrillShape(k.PAD_DRILL_SHAPE_OBLONG)
        pad.SetOrientationDegrees(a.get('angle',0))
        if 'layers' in a:
            layers=k.LSET()
            for name in a['layers']:layers.AddLayer(getattr(k,name.replace('.','_')))
        elif typ=='smd':layers=k.LSET.FrontMask();layers.AddLayer(k.F_Paste)
        else:layers=k.LSET.AllCuMask();layers.AddLayer(k.F_Mask);layers.AddLayer(k.B_Mask)
        if typ=='smd' and 'layers' not in a:layers.AddLayer(k.F_Cu)
        pad.SetLayerSet(layers);f.Add(pad)
    if 'custom_body' in p:
        x,y,xx,yy=p['custom_body']
        for a,z in [((x,y),(xx,y)),((xx,y),(xx,yy)),((xx,yy),(x,yy)),((x,yy),(x,y))]:
            shape=k.PCB_SHAPE();shape.SetShape(k.SHAPE_T_SEGMENT);shape.SetStart(v(*a));shape.SetEnd(v(*z));shape.SetWidth(k.FromMM(.1));shape.SetLayer(k.F_Fab);f.Add(shape)
    return f

def build_board(d,out):
    b=k.BOARD();b.SetCopperLayerCount(2);b.GetDesignSettings().SetBoardThickness(k.FromMM(d.get('thickness_mm',1.6)))
    ds=b.GetDesignSettings();ds.m_MinClearance=k.FromMM(.15);ds.m_TrackMinWidth=k.FromMM(.15);ds.m_ViasMinSize=k.FromMM(.5);ds.m_MinThroughDrill=k.FromMM(.25)
    for net in sorted({net for p in d['parts'] for net in p['nets'].values() if net}):b.Add(k.NETINFO_ITEM(b,net))
    for p in d['parts']:
        if 'custom_pads' in p:f=custom_footprint(p)
        else:
            lib,name=p['fp'].split(':');f=k.FootprintLoad(str(LIB/(lib+'.pretty')),name)
            assert f,'Footprint missing: '+p['fp']
        b.Add(f);f.SetReference(p['ref']);f.SetValue(p['value']);f.SetPosition(v(*p['xy']));f.SetOrientationDegrees(p['angle'])
        f.Reference().SetVisible(False);f.Value().SetVisible(False)
        for g in list(f.GraphicalItems()):
            if isinstance(g,k.PCB_TEXT):g.SetVisible(False)
        padnums={pad.GetNumber() for pad in f.Pads() if pad.GetNumber()}
        assert padnums==set(p['nets']), (p['ref'],'pad/pin mismatch',padnums,set(p['nets']))
        for pad in f.Pads():
            net=p['nets'].get(pad.GetNumber())
            if net:pad.SetNet(b.FindNet(net))
        # Module copper pads are intentional half-holes; keep complete drills
        # so the manufacturer can mill exactly through their centres.
    w,h=d['size_mm']
    for a,z in [((0,0),(w,0)),((w,0),(w,h)),((w,h),(0,h)),((0,h),(0,0))]:segment(b,a,z,k.Edge_Cuts,.05)
    for a in d.get('tracks',[]):
        pts=a['points'];layer=k.F_Cu if a.get('layer','F.Cu')=='F.Cu' else k.B_Cu
        for s,e in zip(pts,pts[1:]):segment(b,s,e,layer,a.get('width',.2),a['net'])
    for a in d.get('vias',[]):
        t=k.PCB_VIA(b);t.SetPosition(v(*a['xy']));t.SetWidth(k.FromMM(a.get('diameter',.6)));t.SetDrill(k.FromMM(a.get('drill',.3)));t.SetViaType(k.VIATYPE_THROUGH);t.SetLayerPair(k.F_Cu,k.B_Cu);t.SetNet(b.FindNet(a['net']));b.Add(t)
    for a in d.get('silkscreen',[]):
        t=k.PCB_TEXT(b);t.SetText(a['text']);t.SetPosition(v(*a['xy']));t.SetTextSize(v(a.get('size',.7),a.get('size',.7)));t.SetTextThickness(k.FromMM(.12));t.SetLayer(k.F_SilkS);b.Add(t)
    pcb=out/(d['name']+'.kicad_pcb');k.SaveBoard(str(pcb),b)
    project={'board':{'design_settings':{'rules':{'min_clearance':.15,'min_track_width':.15,'min_via_diameter':.5,'min_through_hole_diameter':.25,'min_copper_edge_clearance':.25,'min_hole_clearance':.25}}},'net_settings':{'classes':[{'name':'Default','clearance':.15,'track_width':.2,'via_diameter':.6,'via_drill':.3,'diff_pair_width':.2,'diff_pair_gap':.15,'diff_pair_via_gap':.25}],'meta':{'version':4}},'meta':{'version':1}}
    (out/(d['name']+'.kicad_pro')).write_text(json.dumps(project,indent=2))
    assert k.ExportSpecctraDSN(b,str(out/(d['name']+'.dsn')))
    return b

def pour_outline(d,top):
    w,h=d['size_mm']
    return d.get('top_ground_outline') if top and d.get('top_ground_outline') else [[.25,.25],[w-.25,.25],[w-.25,h-.25],[.25,h-.25]]

def add_pours(b,d):
    w,h=d['size_mm'];net=d.get('ground_net','GND')
    for layer in (k.F_Cu,k.B_Cu):
        z=k.ZONE(b);z.SetLayer(layer);z.SetNet(b.FindNet(net));z.SetLocalClearance(k.FromMM(.2));z.SetThermalReliefGap(k.FromMM(.2));z.SetThermalReliefSpokeWidth(k.FromMM(.2));z.SetPadConnection(k.ZONE_CONNECTION_THERMAL);z.SetMinThickness(k.FromMM(.15));o=z.Outline();o.NewOutline()
        for x,y in pour_outline(d,layer==k.F_Cu):o.Append(k.FromMM(x),k.FromMM(y))
        b.Add(z)
    k.ZONE_FILLER(b).Fill(b.Zones())

def export_native(b,d,out,template):
    mm=1/.0254;n.uid=lambda s:uuid.uuid5(uuid.NAMESPACE_URL,d['name']+'/'+s).hex[:16]
    old=n.parse_archive(template);base=next(x['r'] for x in old if x['head']['docType']=='FOOTPRINT')
    dev=next(x for x in old if x['head']['docType']=='DEVICE' and any(a and a.get('title')=='GLOBAL_NET' for h,a in x['r'] if h['type']=='META'))
    flaguuid=next(a['attributes']['Symbol'] for h,a in dev['r'] if h['type']=='META')
    g=next(x for x in old if x['head']['uuid']==flaguuid)
    D=n.Doc;sa=n.sa
    flag=D('SYMBOL','flag');flag.r=copy.deepcopy(g['r']);flag.n=len(g['r']);docs=[flag]
    fd=D('DEVICE','flagdev');fd.put('META',dict(title='GLOBAL_NET',tags=[],source='',images=[],attributes={'Symbol':flag.uuid,'Footprint':'','Name':'NET','Add into BOM':'no'}),'META');docs.append(fd)
    board=D('BOARD','board');board.put('META',dict(title=d['name'],zIndex=1),'META');docs.append(board)
    sch=D('SCH','sch');sch.put('META',dict(title=d['name'],board=board.uuid,zIndex=1),'META');docs.append(sch)
    sheets={}
    for s in d['sheets']:
        sd=D('SCH_PAGE','sheet'+str(s['id']));sd.put('CANVAS',dict(originX=0,originY=0),'CANVAS');sd.put('META',dict(title=s['title'],schematic=sch.uuid,zIndex=s['id']),'META');n.text(sd,d['name'],35,30,14);n.text(sd,'SCHEMATIC / PCB DRAFT - native DRC and bench validation pending',35,55,9)
        for i,line in enumerate(s.get('notes',[])):n.text(sd,line,35,80+17*i,8)
        sheets[s['id']]=sd
    def layers(doc):
        for h,a in base:
            if h['type'] in ('CANVAS','LAYER','ACTIVE_LAYER'):
                a=copy.deepcopy(a)
                if h['type']=='LAYER' and a.get('layerType')=='SIGNAL':a.update(use=False,show=False)
                doc.put(h['type'],a,h['id'])
    def poly(doc,pts,layer,width=.1):
        return doc.put('POLY',dict(layerId=layer,groupId='',locked=False,zIndex=doc.n,partitionId=None,polyType='BOARD_OUTLINE' if layer==11 else 'NORMAL',netName='',width=width*mm,path=[pts[0][0]*mm,-pts[0][1]*mm,'L']+[q for x,y in pts[1:] for q in (x*mm,-y*mm)],specialColor=None))
    pcb=D('PCB','pcb');layers(pcb);pcb.put('META',dict(title=d['name'],board=board.uuid,parent='',source='',zIndex=1),'META')
    w,h=d['size_mm'];poly(pcb,[(0,0),(w,0),(w,h),(0,h),(0,0)],11,.05)
    fmap={f.GetReference():f for f in b.GetFootprints()}
    def footprint(p):
        f=fmap[p['ref']];ft=D('FOOTPRINT','fp'+p['ref']);layers(ft);padids=[]
        for pad in f.Pads():
            x,y=xy(pad.GetFPRelativePosition());pw,ph=xy(pad.GetSize());dw,dh=xy(pad.GetDrillSize());shape=pad.GetShape()
            default=dict(padType='ELLIPSE' if shape==k.PAD_SHAPE_CIRCLE else 'OVAL' if shape==k.PAD_SHAPE_OVAL else 'RECT',width=pw*mm,height=ph*mm)
            if shape==k.PAD_SHAPE_ROUNDRECT:default['radius']=pad.GetRoundRectRadiusRatio()*200
            a=dict(layerId=12 if dw else 1 if pad.IsOnLayer(k.F_Cu) else 2,groupId='',locked=False,zIndex=ft.n,partitionId=None,netName='',num=pad.GetNumber(),centerX=x*mm,centerY=-y*mm,padAngle=pad.GetFPRelativeOrientation().AsDegrees(),hole=dict(holeType='ROUND' if abs(dw-dh)<1e-6 else 'SLOT',width=max(dw,dh)*mm,height=min(dw,dh)*mm),defaultPad=default,specialPad=[],padOffsetX=0,padOffsetY=0,relativeAngle=90 if dh>dw else 0,plated=pad.GetAttribute()!=k.PAD_ATTRIB_NPTH,padType='NORMAL',topSolderExpansion=0,bottomSolderExpansion=0,topPasteExpansion=0 if pad.IsOnLayer(k.F_Paste) else -1000,bottomPasteExpansion=0 if pad.IsOnLayer(k.B_Paste) else -1000,connectMode='DIRECT' if pad.GetLocalZoneConnection()==k.ZONE_CONNECTION_FULL else None,spokeSpace=None,spokeWidth=None,spokeAngle=None,unusedInnerLayers=[],refs=[])
            padids.append((pad.GetNumber(),ft.put('PAD',a),pad.GetNetname()))
        # Copy graphics with placement transformation reversed.
        f0=k.FOOTPRINT(f);f0.SetOrientationDegrees(0);f0.SetPosition(v(0,0))
        for g in f0.GraphicalItems():
            if not isinstance(g,k.PCB_SHAPE) or g.GetLayer() not in (k.F_Fab,k.F_SilkS,k.F_CrtYd):continue
            x,y=xy(g.GetStart());xx,yy=xy(g.GetEnd());shape=g.GetShape();pts=[]
            if shape==k.SHAPE_T_SEGMENT:pts=[(x,y),(xx,yy)]
            elif shape==k.SHAPE_T_RECT:pts=[(x,y),(xx,y),(xx,yy),(x,yy),(x,y)]
            elif shape==k.SHAPE_T_CIRCLE:
                r=math.hypot(xx-x,yy-y);pts=[(x+r*math.cos(t*math.pi/16),y+r*math.sin(t*math.pi/16)) for t in range(33)]
            if pts:poly(ft,pts,3 if g.GetLayer()==k.F_SilkS else 9,.07)
        ft.put('META',dict(title=p.get('fp',p['ref'])+'_'+p['ref'],tags=[],source='KiCad geometry; editable prototype, not fabrication release'),'META');return ft,padids
    # Automatic sheet layout allocates enough vertical height for all pin rows.
    loc={}
    for s in d['sheets']:
        ps=[p for p in d['parts'] if p['sheet']==s['id']];y=150+17*len(s.get('notes',[]))
        for start in range(0,len(ps),3):
            row=ps[start:start+3];height=max(max(60,(math.ceil(len(p['nets'])/2)+1)*20) if len(p['nets'])>2 else 35 for p in row)
            for col,p in enumerate(row):loc[p['ref']]=p.get('sch_xy',[220+col*480,y+height/2])
            y+=height+100
    expected=[];mapping=[]
    for p in d['parts']:
        sym,pos,height=n.symbol(p);ft,pads=footprint(p)
        dev=D('DEVICE','dev'+p['ref']);dev.put('META',dict(title=p['value'],tags=[],source='',images=[],attributes={'Symbol':sym.uuid,'Footprint':ft.uuid,'Name':p['value'],'Value':p['value'],'Designator':re.sub(r'\d+$','?',p['ref']),'Description':p['notes'],'Add into BOM':'no' if p.get('dnp') or p['kind']=='TP' else 'yes'}),'META');docs.extend([sym,ft,dev]);sd=sheets[p['sheet']];x,y=loc[p['ref']]
        inst=sd.put('COMPONENT',dict(locked=False,zIndex=sd.n,partId='1',groupId='',x=x,y=y,rotation=0,isMirror=False,attrs={}))
        for key,val in [('Device',dev.uuid),('Symbol',sym.uuid),('Footprint',ft.uuid),('Unique ID',n.uid('instance'+p['ref'])),('Name',p['value']),('Designator',p['ref'])]:sa(sd,inst,key,val,x-75,y-height/2-(25 if key=='Designator' else 10),key in ('Name','Designator'),8)
        for num,net in p['nets'].items():
            dx,dy,rot=pos[num];px,py=x+dx,y+dy
            if net is None:
                pinid=next(a['parentId'] for q,a in sym.r if q['type']=='ATTR' and a.get('key')=='Pin Number' and a.get('value')==num);sa(sd,inst+'-'+pinid,'NO_CONNECT','yes',px,py);continue
            ex=px+(-25 if rot==0 else 25);n.line(sd,px,py,ex,py,wire=True);ni=sd.put('COMPONENT',dict(locked=False,zIndex=sd.n,partId='1',groupId='',x=ex,y=py,rotation=0 if rot==0 else 180,isMirror=False,attrs={}))
            sa(sd,ni,'Device',fd.uuid);sa(sd,ni,'Symbol',flag.uuid);sa(sd,ni,'Name',net,ex-10 if rot==0 else ex+10,py,True,5.5,'RIGHT_MIDDLE' if rot==0 else 'LEFT_MIDDLE');expected.append((p['ref'],num,net))
        ox,oy=p['xy'];ci=pcb.put('COMPONENT',dict(partitionId='',groupId=0,layerId=1,x=ox*mm,y=-oy*mm,angle=p['angle'],attrs={'Unique ID':n.uid('instance'+p['ref']),'FootprintName':ft.uuid,'UserDocLink':'','Channel ID':'$1'+inst},locked=False,zIndex=pcb.n))
        for key,val in [('Device',dev.uuid),('Footprint',ft.uuid),('Name',p['value']),('Designator',p['ref'])]:n.pcb_attr(pcb,ci,key,val,ox*mm,-oy*mm,False)
        for num,pid,net in pads:pcb.put('PAD_NET',dict(padNet=net,padLen=None,propagationDelay=None),json.dumps(['PAD_NET',ci,'',pid],separators=(',',':')))
        mapping.append(dict(ref=p['ref'],schematic_component=inst,pcb_component=ci,symbol=sym.uuid,footprint=ft.uuid,pad_nets=[{'pad':num,'net':net} for num,pid,net in pads]))
    for net in sorted({t[2] for t in expected}):pcb.put('NET',dict(netType=None,specialColor=None,retLine=True,differentialName=None,isPositiveNet=False,equalLengthGroupName=None),json.dumps(['NET',net],separators=(',',':')))
    for t in b.GetTracks():
        if isinstance(t,k.PCB_VIA):
            x,y=xy(t.GetPosition());pcb.put('VIA',dict(partitionId='',groupId=0,netName=t.GetNetname(),ruleName='',centerX=x*mm,centerY=-y*mm,holeDiameter=k.ToMM(t.GetDrill())*mm,viaDiameter=k.ToMM(t.GetWidth(k.F_Cu))*mm,viaType='NORMAL',topSolderExpansion=-1000,bottomSolderExpansion=-1000,locked=False,zIndex=pcb.n,unusedInnerLayers=[]))
        else:
            x,y=xy(t.GetStart());xx,yy=xy(t.GetEnd());pcb.put('LINE',dict(layerId=1 if t.GetLayer()==k.F_Cu else 2,groupId='',locked=False,zIndex=pcb.n,partitionId=None,netName=t.GetNetname(),width=k.ToMM(t.GetWidth())*mm,startX=x*mm,startY=-y*mm,endX=xx*mm,endY=-yy*mm))
    if b.Zones():
        for layer in (1,2):
            outline=pour_outline(d,layer==1);path=[outline[0][0]*mm,-outline[0][1]*mm,'L']+[c for x,y in outline[1:]+outline[:1] for c in (x*mm,-y*mm)]
            pcb.put('POUR',dict(partitionId='',groupId=0,netName=d.get('ground_net','GND'),layerId=layer,width=.2,name='GND_'+str(layer),order=layer,path=[path],pourType={'pourType':'SOLID','fineness':0},keepIsland=False,locked=False,zIndex=pcb.n))
    vp=next(x for x in old if x['head']['docType']=='PCB')
    for hd,a in vp['r']:
        if hd['type'] in ('RULE','LAYER_PHYS'):pcb.put(hd['type'],copy.deepcopy(a),hd['id'])
    for t in b.GetDrawings():
        if isinstance(t,k.PCB_TEXT) and t.GetLayer()==k.F_SilkS:
            x,y=xy(t.GetPosition());pcb.put('STRING',dict(layerId=3,groupId='',locked=False,zIndex=pcb.n,partitionId=None,x=x*mm,y=-y*mm,text=t.GetText(),origin='CENTER_MIDDLE',fontFamily='default',fontSize=k.ToMM(t.GetTextHeight())*mm,strokeWidth=k.ToMM(t.GetTextThickness())*mm,italic=False,expansion=0,angle=t.GetTextAngle().AsDegrees(),reverse=False,mirror=False,specialColor=None))
        elif isinstance(t,k.PCB_SHAPE) and t.GetLayer()==k.F_SilkS and t.GetShape()==k.SHAPE_T_SEGMENT:
            poly(pcb,[xy(t.GetStart()),xy(t.GetEnd())],3,k.ToMM(t.GetWidth()))
    docs.extend(sheets.values());docs.append(pcb);cfg=D('CONFIG','config');cfg.uuid='CONFIG';cfg.put('META',{'defaultSheet':sheets[d['sheets'][0]['id']].uuid},'META');docs.append(cfg)
    with zipfile.ZipFile(out/(d['name']+'.epro2'),'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('project2.json',json.dumps(dict(title=d['name'],cbb_project=False,editorVersion='3.2.175',introduction='Schematic and PCB prototype',description='NOT FOR FABRICATION - native DRC pending',tags='[]')))
        z.writestr(d['name']+'.epru',''.join(doc.serialize() for doc in docs))
    (out/'expected-pin-nets.json').write_text(json.dumps(expected,indent=2));(out/'native-mapping.json').write_text(json.dumps(mapping,indent=2))

def export_geometry(b,d,out):
    parts=[]
    for f in b.GetFootprints():
        p={'ref':f.GetReference(),'xy':xy(f.GetPosition()),'angle':f.GetOrientationDegrees(),'pads':[]}
        for pad in f.Pads():p['pads'].append({'num':pad.GetNumber(),'net':pad.GetNetname(),'xy':xy(pad.GetPosition()),'size':xy(pad.GetSize()),'drill':xy(pad.GetDrillSize()),'angle':pad.GetOrientationDegrees()})
        parts.append(p)
    (out/'component-geometry.json').write_text(json.dumps(parts,indent=2))
    with (out/'BOM.csv').open('w',newline='') as f:
        cw=csv.writer(f);cw.writerow(['Reference','Value','Footprint','DNP','Notes'])
        for p in d['parts']:cw.writerow([p['ref'],p['value'],p.get('fp','CUSTOM'),bool(p.get('dnp')),p['notes']])

def export_custom_library(b,out):
    lib=out.resolve()/'AsterCustom.pretty';lib.mkdir(exist_ok=True)
    plug=k.PCB_IO_MGR.FindPlugin(k.PCB_IO_MGR.KICAD_SEXP)
    for f in b.GetFootprints():
        if str(f.GetFPID().GetLibNickname())!='AsterCustom':continue
        copyfp=k.FOOTPRINT(f);copyfp.SetPosition(v(0,0));copyfp.SetOrientationDegrees(0);plug.FootprintSave(str(lib),copyfp)
    (out/'fp-lib-table').write_text('(fp_lib_table (version 7) (lib (name "AsterCustom")(type "KiCad")(uri "${KIPRJMOD}/AsterCustom.pretty")(options "")(descr "Project custom footprints")))\n')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('design',type=Path);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--template',type=Path,default=DEFAULT_TEMPLATE);ap.add_argument('--ses',type=Path);ap.add_argument('--existing',action='store_true');ap.add_argument('--pours',action='store_true');args=ap.parse_args()
    d=normalize(json.loads(args.design.read_text()));args.out.mkdir(parents=True,exist_ok=True)
    pcb=args.out/(d['name']+'.kicad_pcb')
    b=k.LoadBoard(str(pcb)) if args.existing else build_board(d,args.out)
    if args.ses:assert k.ImportSpecctraSES(b,str(args.ses))
    if args.pours:add_pours(b,d)
    k.SaveBoard(str(pcb),b);export_native(b,d,args.out,args.template);export_geometry(b,d,args.out);export_custom_library(b,args.out)
    (args.out/'design-manifest.json').write_text(json.dumps(d,ensure_ascii=False,indent=2))
    print(json.dumps({'board':str(pcb),'parts':len(d['parts']),'tracks_and_vias':len(b.GetTracks()),'status':'NOT_FOR_FAB; native checks and bench validation pending'},indent=2))

if __name__=='__main__':main()

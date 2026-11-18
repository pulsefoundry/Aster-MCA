import json, math, re, time, uuid, zipfile
from pathlib import Path

def uid(s):
    return uuid.uuid5(uuid.NAMESPACE_URL, "aster-nano-v04/"+s).hex[:16]


def parse_archive(path):
    with zipfile.ZipFile(path) as z:
        s=z.read(next(n for n in z.namelist() if n.endswith('.epru'))).decode()
    docs=[]
    for line in s.splitlines():
        if not line.strip():continue
        h,a=(line[:-1] if line.endswith('|') else line).split('||',1)
        h=json.loads(h);a=json.loads(a) if a else None
        if h['type']=='DOCHEAD':docs.append({'head':a,'r':[]})
        else:docs[-1]['r'].append((h,a))
    return docs

class Doc:
    def __init__(self,typ,key):
        self.typ=typ;self.uuid=uid(key);self.r=[];self.n=0
    def put(self,typ,a,id=None):
        self.n+=1;id=id or 'n'+str(self.n)
        self.r.append((dict(type=typ,ticket=self.n,id=id),a));return id
    def serialize(self):
        head={'docType':self.typ,'uuid':self.uuid,'client':uid('client'),'updateTime':int(time.time()*1000),'version':'1','editVersion':'3.2.175'}
        def row(h,a):return json.dumps(h,separators=(',',':'))+'||'+json.dumps(a,ensure_ascii=False,separators=(',',':'))+'|\n'
        return row({'type':'DOCHEAD'},head)+''.join(row(h,a) for h,a in self.r)

def sa(doc,parent,key,val,x=None,y=None,visible=False,size=7,align='LEFT_MIDDLE',part=None):
    a=dict(groupId='',locked=False,zIndex=doc.n,parentId=parent,key=key,value=str(val),keyVisible=False,valueVisible=visible,x=x,y=y,rotation=0,color=None,fillColor=None,fontFamily='default',fontSize=size,strikeout=False,underline=False,italic=False,fontWeight=False,align=align,version='2.0')
    if part:a['partId']=part
    return doc.put('ATTR',a)

def line(doc,x1,y1,x2,y2,part=None,wire=False):
    if wire:
        w=doc.put('WIRE',dict(groupId='',locked=False,zIndex=doc.n))
        return doc.put('LINE',dict(lineGroup=w,startX=x1,startY=y1,endX=x2,endY=y2,strokeColor='#009600',strokeStyle='SOLID',fillColor=None,strokeWidth=1,fillStyle='NONE'))
    a=dict(groupId='',locked=False,zIndex=doc.n,points=[dict(x=x1,y=y1),dict(x=x2,y=y2)],closed=False,strokeColor=None,strokeWidth=1,strokeStyle='SOLID',fillStyle='NONE',fillColor=None)
    if part:a['partId']=part
    return doc.put('POLY',a)

def text(doc,s,x,y,size=9):
    return doc.put('TEXT',dict(groupId='',locked=False,zIndex=doc.n,x=x,y=y,rotation=0,value=s,color='#000080',fillColor=None,fontFamily='default',fontSize=size,strikeout=False,underline=False,italic=False,fontWeight=False,align='LEFT_BOTTOM',version='2.0'))

def symbol(p):
    d=Doc('SYMBOL','symbol/'+p['ref']);d.put('CANVAS',dict(originX=0,originY=0),'CANVAS');d.put('PART',{'title':'1'},'1')
    n=len(p['nets']);kind=p['kind'];pos={}
    if n<=2:
        pos={k:((-40,0,0) if i==0 else (40,0,180)) for i,k in enumerate(p['nets'])}
        if kind=='R':
            for a,b in [((-25,-7),(25,-7)),((25,-7),(25,7)),((25,7),(-25,7)),((-25,7),(-25,-7)),((-30,0),(-25,0)),((25,0),(30,0))]:line(d,*a,*b,part='1')
        elif kind in ('C','FILM','EL'):
            for a,b in [((-30,0),(-5,0)),((5,0),(30,0)),((-5,-14),(-5,14)),((5,-14),(5,14))]:line(d,*a,*b,part='1')
            if kind=='EL':line(d,-16,-16,-10,-16,part='1');line(d,-13,-19,-13,-13,part='1')
        elif kind in ('D','LED'):
            for a,b in [((-30,0),(-10,0)),((-10,-12),(-10,12)),((-10,0),(10,-12)),((10,-12),(10,12)),((10,12),(-10,0)),((10,0),(30,0))]:line(d,*a,*b,part='1')
        else:
            line(d,-30,-10,30,-10,part='1');line(d,-30,10,30,10,part='1')
        height=35
    else:
        left=math.ceil(n/2);height=max(60,(left+1)*20)
        for i,k in enumerate(p['nets']):
            pos[k]=(-90,(i-(left-1)/2)*20,0) if i<left else (90,(i-left-(n-left-1)/2)*20,180)
        d.put('RECT',dict(partId='1',groupId='',locked=False,zIndex=d.n,dotX1=-75,dotY1=-height/2,dotX2=75,dotY2=height/2,radiusX=0,radiusY=0,rotation=0,strokeColor=None,strokeWidth=1,strokeStyle='SOLID',fillColor=None,fillStyle='NONE'))
    for k,(x,y,r) in pos.items():
        pin=d.put('PIN',dict(partId='1',groupId='',locked=False,zIndex=d.n,display=True,x=x,y=y,length=10 if n<=2 else 15,rotation=r,color=None,pinShape='NONE'))
        name=p['names'].get(k,k)
        sa(d,pin,'Pin Name',name,x+18 if r==0 else x-18,y,n>2,5.5,'LEFT_MIDDLE' if r==0 else 'RIGHT_MIDDLE','1')
        sa(d,pin,'Pin Number',k,x+3 if r==0 else x-3,y-6,True,5,'LEFT_MIDDLE' if r==0 else 'RIGHT_MIDDLE','1')
        # Explicit unused pins remain present and are annotated in the schematic.
        typ='Passive'
        if name in ('IN+','IN-','INPUT','IN','LOGIC','R/C','CE','A0','/CS','/OE','DIR','REF IN','10V IN','20V IN'):typ='IN'
        if name in ('OUT','OUTPUT','REF OUT','STS','COLLECTOR','T1OUT','T2OUT','R1OUT','R2OUT'):typ='OUT'
        if name in ('V+','V-','VCC','VEE','VLOGIC','VDD','GND','VLOGIC','AVCC','VL','DIGITAL COM','ANALOG COM'):typ='Power'
        if name.startswith('DB') or re.match(r'^[AB][1-8]$',name):typ='Passive'
        sa(d,pin,'Pin Type',typ,part='1')
    sa(d,'','Name',p['value'],part='1');sa(d,'','Designator',p['ref'][0]+'?',part='1')
    d.put('META',dict(title=p['value']+'_'+p['ref'],tags=[],docType=2,source=''),'META')
    return d,pos,height

def pcb_attr(d,parent,key,val,x,y,vis=False,size=40):
    return d.put('ATTR',dict(partitionId='',groupID=0,parentId=parent,layerId=3,x=x,y=y,key=key,value=str(val),keyVisible=False,valueVisible=vis,fontFamily='default',fontSize=size,strokeWidth=5,bold=0,italic=0,origin='LEFT_BOTTOM',angle=0,reverse=False,expansion=0,mirror=False,locked=False,zIndex=d.n,specialColor=None))

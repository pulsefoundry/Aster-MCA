#!/usr/bin/env python3
"""Mark pre-routed critical nets protected in a Specctra DSN, not UI state.

Only existing wire/via records on named nets are changed. This does not create
a complete route or exempt a route from clearance checks.
"""
from pathlib import Path
import argparse,re,json

def protect(text,nets):
    text=text.replace('(string_quote ")','(string_quote QUOTE_TOKEN)')
    spans=[];stack=[];quoted=False;escape=False
    for i,c in enumerate(text):
        if escape:escape=False;continue
        if c=='\\' and quoted:escape=True;continue
        if c=='"':quoted=not quoted;continue
        if quoted:continue
        if c=='(':stack.append(i)
        elif c==')':
            start=stack.pop();record=text[start:i+1]
            if not re.match(r'\((wire|via)\s',record):continue
            m=re.search(r'\(net\s+("[^"]+"|[^\s()]+)\)',record)
            if m and m.group(1).strip('"') in nets:
                new=re.sub(r'\(type\s+[^()]+\)','(type protect)',record)
                if new==record and '(type protect)' not in record:new=record[:-1]+'(type protect))'
                spans.append((start,i+1,new))
    for start,end,new in reversed(spans):text=text[:start]+new+text[end:]
    return text.replace('(string_quote QUOTE_TOKEN)','(string_quote ")'),len(spans)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('input',type=Path);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--net',action='append',default=[]);a=ap.parse_args()
    t,c=protect(a.input.read_text(),set(a.net));a.out.write_text(t);print(json.dumps({'protected_records':c,'nets':a.net,'output':str(a.out)}))

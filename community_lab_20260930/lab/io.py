from __future__ import annotations
import hashlib,json,os,tempfile
from pathlib import Path

def read_json(path):
    with open(path,encoding='utf-8') as f:return json.load(f)

def write_json(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(obj,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()

def graph(path):
    d=read_json(path);n=d['n']
    if type(n) is not int or n<1:raise ValueError('n must be a positive integer')
    edges=[];seen=set()
    for row in d['edges']:
        if len(row)!=2 or any(type(x) is not int for x in row):raise ValueError('Edges must contain two integer IDs')
        u,v=row
        if not 0<=u<v<n:raise ValueError(f'Expected canonical 0<=u<v<n, got {row}')
        if (u,v) in seen:raise ValueError('Duplicate edge')
        seen.add((u,v));edges.append((u,v))
    return n,edges

def cover(path,n):
    d=read_json(path)
    if not isinstance(d,dict) or 'communities' not in d:raise ValueError('Expected communities JSON object')
    out=[];empty=0;within_duplicates=0
    for c in d['communities']:
        if not isinstance(c,list) or any(type(v) is not int or not 0<=v<n for v in c):
            raise ValueError('Cover has invalid node IDs')
        within_duplicates+=len(c)-len(set(c))
        if not c:empty+=1;continue
        out.append(frozenset(c))
    return out,{'empty_groups_removed':empty,'within_group_duplicates_removed':within_duplicates,
                'duplicate_groups_retained':len(out)-len(set(out))}

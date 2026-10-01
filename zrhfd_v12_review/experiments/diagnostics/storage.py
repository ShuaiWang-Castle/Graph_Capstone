"""Atomic immutable diagnostic artifacts, separate from method measurements."""
from pathlib import Path
from fractions import Fraction
from datetime import datetime,timezone
import hashlib
import json
import math
import os
import uuid
import numpy as np

PROJECT=Path(__file__).resolve().parents[2]


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def stamp():return datetime.now(timezone.utc).isoformat()


def clean(value):
    if isinstance(value,dict):return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple,set,np.ndarray)):return [clean(v) for v in value]
    if isinstance(value,np.generic):return clean(value.item())
    if isinstance(value,Fraction):return str(value)
    if isinstance(value,float) and not math.isfinite(value):raise ValueError('Nonfinite diagnostic value')
    return value


def publish(path,content):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_bytes()!=content:raise RuntimeError('Immutable artifact differs: '+str(path))
        return
    temporary=path.parent/('.'+path.name+'.partial-'+str(uuid.uuid4()))
    with temporary.open('xb') as stream:stream.write(content);stream.flush()
    try:os.link(temporary,path)
    except FileExistsError:
        if path.read_bytes()!=content:raise RuntimeError('Concurrent immutable artifact differs')
    finally:temporary.unlink(missing_ok=True)


def write_json(path,value):
    publish(path,(json.dumps(clean(value),sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode())


def write_scores(path,score):
    import io
    stream=io.BytesIO();np.save(stream,np.asarray(score,dtype='<f8'),allow_pickle=False);publish(path,stream.getvalue())


def scoped_output(path):
    resolved=(PROJECT/path).resolve()
    if not resolved.is_relative_to((PROJECT/'results/diagnostics').resolve()):raise ValueError('Diagnostic output outside assigned boundary')
    return resolved

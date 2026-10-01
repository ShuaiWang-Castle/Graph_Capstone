"""Transparent, byte-preserving local compression of terminal M6 artifacts.

Compression follows measurement termination. No graph inputs or live files
are changed. Original paths stay readable by frozen runners and summaries.
Portable delivery uses ZIP separately; APFS compression is optional storage.
"""
from pathlib import Path
import hashlib,json,os,platform,subprocess,time,datetime

def sha_file(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def compress_terminal(directory):
    directory=Path(directory)
    terminal=directory/'terminal.json'
    if not terminal.exists() or json.loads(terminal.read_text()).get('status') in ('running','STARTED'):
        raise RuntimeError('Only terminal M6 attempts may be compressed')
    receipt=directory/'TRANSPARENT_STORAGE.json'
    if receipt.exists():return json.loads(receipt.read_text())
    started=time.perf_counter();records=[]
    selected=[p for p in sorted(directory.rglob('*')) if p.is_file() and not p.is_symlink()
              and p.name!='TRANSPARENT_STORAGE.json' and not p.name.endswith('.compression-tmp')]
    for path in selected:
        before=path.stat();digest=sha_file(path);entry={'path':str(path.relative_to(directory)),
           'sha256':digest,'logical_bytes':before.st_size,'allocated_before_bytes':before.st_blocks*512}
        if platform.system()=='Darwin' and before.st_size>=65536 and not(before.st_flags & 0x20):
            temporary=path.with_name('.'+path.name+'.compression-tmp')
            if temporary.exists():raise RuntimeError('Interrupted compression copy retained; original still present: '+str(path))
            command=['/usr/bin/ditto','--hfsCompression',str(path),str(temporary)]
            result=subprocess.run(command,capture_output=True,text=True)
            if result.returncode or sha_file(temporary)!=digest:
                raise RuntimeError('Compression did not preserve raw bytes: '+str(path)+' '+result.stderr)
            entry.update(actual_command=command,compression_flag_present=bool(temporary.stat().st_flags & 0x20))
            os.replace(temporary,path)
        entry['allocated_after_bytes']=path.stat().st_blocks*512
        if sha_file(path)!=digest:raise RuntimeError('Stored raw hash changed')
        records.append(entry)
    value={'schema_version':1,'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
       'terminal_status':json.loads(terminal.read_text())['status'],'files':records,
       'all_original_paths_and_bytes_unchanged':True,'filesystem_compression_only':True,
       'offline_storage_seconds':time.perf_counter()-started,'included_in_measurement_runtime':False,
       'source_sha256':{str(Path(__file__).name):sha_file(__file__)},
       'allocated_before_bytes':sum(r['allocated_before_bytes'] for r in records),
       'allocated_after_bytes':sum(r['allocated_after_bytes'] for r in records)}
    with receipt.open('x') as stream:json.dump(value,stream,ensure_ascii=False,indent=2);stream.write('\n')
    return value

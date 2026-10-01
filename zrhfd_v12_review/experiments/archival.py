"""Lossless post-measurement raw storage; never changes a measurement worker.

Original bytes and relative names remain in a verified ZIP. Small execution
receipts remain directly readable. Readers resolve original paths through the
archive index. Compression and verification time is an offline storage cost.
"""
from pathlib import Path
import datetime,hashlib,json,os,time,zipfile

ROOT=Path(__file__).resolve().parents[1]
KEEP={'receipt.json','request.json','execution_request.json','process_started.json',
      'terminal.json','controller.json','ARCHIVE.json','RAW_RECORDS.zip'}
STORAGE_POLICY='mixed_zip_v002: plaintext >=65536 bytes LZMA; smaller/plain other DEFLATE6; already encoded STORE'
TERMINAL_STATUSES={'COMPLETED','FAILED','TIMEOUT','MEMORY_LIMIT','INTERRUPTED',
                   'PARTIAL_TIMEOUT','PARTIAL_UPDATE_BUDGET','ABANDONED_PREVIOUS_RUN'}

def compression_for(path):
    path=Path(path)
    if path.suffix.lower() in {'.zip','.gz','.png','.jpg','.jpeg','.pdf','.xz','.zst'}:return zipfile.ZIP_STORED
    if path.suffix.lower() in {'.json','.jsonl','.log','.txt','.csv','.md'} and path.stat().st_size>=65536:
        return zipfile.ZIP_LZMA
    return zipfile.ZIP_DEFLATED

def digest_stream(stream):
    h=hashlib.sha256()
    for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def read_bytes(path):
    path=Path(path)
    if path.exists():return path.read_bytes()
    for parent in path.parents:
        index=parent/'ARCHIVE.json'
        if index.exists():
            metadata=json.loads(index.read_text());member=str(path.relative_to(parent))
            if member in metadata['files']:
                with zipfile.ZipFile(parent/metadata['archive']) as archive:data=archive.read(member)
                if hashlib.sha256(data).hexdigest()!=metadata['files'][member]['sha256']:
                    raise RuntimeError('Archived bytes differ: '+str(path))
                return data
        if parent==ROOT:break
    raise FileNotFoundError(path)

def read_json(path):return json.loads(read_bytes(path))

def verify_archive(directory,metadata,cleanup_expanded=False):
    directory=Path(directory);archive_path=directory/metadata['archive']
    with archive_path.open('rb') as stream:
        if digest_stream(stream)!=metadata['archive_sha256']:raise RuntimeError('Archive file SHA256 differs')
    with zipfile.ZipFile(archive_path) as archive:
        if set(archive.namelist())!=set(metadata['files']):raise RuntimeError('Archive inventory differs')
        for name,record in metadata['files'].items():
            if 'zip_compression_method' in record and archive.getinfo(name).compress_type!=record['zip_compression_method']:
                raise RuntimeError('Archive compression metadata differs: '+name)
            with archive.open(name) as stream:
                if digest_stream(stream)!=record['sha256']:raise RuntimeError('Archive member SHA256 differs: '+name)
            expanded=directory/name
            if expanded.exists():
                with expanded.open('rb') as stream:
                    if digest_stream(stream)!=record['sha256']:raise RuntimeError('Expanded copy differs: '+name)
                if cleanup_expanded:expanded.unlink()
    return metadata

def archive_completed_attempt(directory):
    directory=Path(directory).resolve()
    if not directory.is_relative_to(ROOT/'results'):
        raise ValueError('Archive only project experiment results')
    index=directory/'ARCHIVE.json'
    receipt=directory/'receipt.json'
    if not receipt.exists():raise RuntimeError('No terminal receipt; active artifacts cannot be archived')
    receipt_bytes=receipt.read_bytes();terminal=json.loads(receipt_bytes)
    if not isinstance(terminal,dict) or terminal.get('status') not in TERMINAL_STATUSES:
        raise RuntimeError('Missing, active or unknown terminal status; retain all expanded artifacts')
    receipt_sha=hashlib.sha256(receipt_bytes).hexdigest()
    if index.exists():
        metadata=json.loads(index.read_text())
        if metadata.get('terminal_status')!=terminal['status'] or metadata.get('terminal_receipt_sha256',receipt_sha)!=receipt_sha:
            raise RuntimeError('Terminal receipt changed after archival; do not clean expanded copies')
        return verify_archive(directory,metadata,cleanup_expanded=True)
    started=time.perf_counter();files={}
    selected=[p for p in sorted(directory.rglob('*')) if p.is_file() and p.name not in KEEP and not p.name.endswith('.partial-archive')]
    if any(p.is_symlink() for p in selected):raise ValueError('Refuse symlink archival')
    temporary=directory/'RAW_RECORDS.zip.partial-archive';final=directory/'RAW_RECORDS.zip'
    if temporary.exists():raise RuntimeError('Interrupted temporary archive needs explicit recovery; original expanded records preserved')
    for path in selected:
        with path.open('rb') as stream:sha=digest_stream(stream)
        files[str(path.relative_to(directory))]={'sha256':sha,'bytes':path.stat().st_size}
    if not final.exists():
        with zipfile.ZipFile(temporary,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as archive:
            for path in selected:
                method=compression_for(path)
                archive.write(path,str(path.relative_to(directory)),compress_type=method,
                              compresslevel=6 if method==zipfile.ZIP_DEFLATED else None)
        stored=temporary
    else:
        # A previous interruption may occur after rename and before index write.
        # No expanded bytes were removed yet; reconstruct and verify that index.
        stored=final
    with zipfile.ZipFile(stored) as archive:
        if set(archive.namelist())!=set(files):raise RuntimeError('Archive inventory differs')
        for name,record in files.items():
            record['zip_compression_method']=archive.getinfo(name).compress_type
            with archive.open(name) as stream:
                if digest_stream(stream)!=record['sha256']:raise RuntimeError('Archive verification failed: '+name)
    with stored.open('rb') as stream:archive_sha=digest_stream(stream)
    if stored==temporary:os.rename(temporary,final)
    metadata={'schema_version':2,'archive':final.name,'archive_sha256':archive_sha,
       'archive_created_by_this_call':stored==temporary,
       'storage_policy':STORAGE_POLICY if stored==temporary else 'preexisting archive recovered without re-encoding; actual methods recorded per member',
       'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
       'files':files,'terminal_status':terminal.get('status'),'terminal_receipt_sha256':receipt_sha,
       'original_paths_resolvable_with':'experiments.archival.read_bytes/read_json',
       'all_original_bytes_preserved':True,'verification':'every ZIP member SHA256 checked before removing expanded copy',
       'expanded_bytes':sum(v['bytes'] for v in files.values()),'archive_bytes':final.stat().st_size,
       'offline_archive_and_verification_seconds':time.perf_counter()-started,
       'included_in_measurement_runtime':False}
    metadata['storage_source_sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
       for p in (Path(__file__).resolve(),ROOT/'experiments/run_m5_archived.py')}
    index_temporary=directory/'ARCHIVE.json.partial-archive';suffix=0
    while index_temporary.exists():
        suffix+=1;index_temporary=directory/f'ARCHIVE-{suffix}.json.partial-archive'
    with index_temporary.open('x') as stream:
        json.dump(metadata,stream,ensure_ascii=False,indent=2);stream.write('\n')
    os.rename(index_temporary,index)
    for path in selected:
        with path.open('rb') as stream:
            if digest_stream(stream)!=files[str(path.relative_to(directory))]['sha256']:
                raise RuntimeError('Source changed before removing expanded copy; both representations preserved')
        path.unlink()
    return metadata

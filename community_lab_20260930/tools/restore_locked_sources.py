#!/usr/bin/env python3
"""Restore audited actual source bytes into a NEW workspace; never overwrite."""
from pathlib import Path,PurePosixPath
import hashlib,json,os,shutil,tarfile,tempfile
ROOT=Path(__file__).resolve().parents[1]
def main():
 archive=ROOT/'provenance/locked_source_trees.tar.gz';manifest=json.loads((ROOT/'provenance/locked_source_trees_manifest.json').read_text());target=ROOT/'external'
 if target.exists():raise FileExistsError('external exists; preserve it and choose a fresh reproduction workspace')
 if hashlib.sha256(archive.read_bytes()).hexdigest()!=manifest['sha256']:raise ValueError('Source archive SHA-256 mismatch')
 expected={x['path']:x for x in manifest['files']};parent=Path(tempfile.mkdtemp(prefix='.sources_',dir=ROOT));seen=set()
 try:
  with tarfile.open(archive,'r:gz') as t:
   for member in t:
    rel=PurePosixPath(member.name)
    if rel.is_absolute() or '..' in rel.parts or '\\' in member.name or not rel.parts or rel.parts[0]!='external' or not member.isfile():raise ValueError('Unsupported/unsafe archive member: '+member.name)
    if member.name not in expected or member.name in seen:raise ValueError('Unlisted or duplicate archive member')
    info=expected[member.name];dest=parent.joinpath(*rel.parts);dest.parent.mkdir(parents=True,exist_ok=True);h=hashlib.sha256();count=0
    with t.extractfile(member) as src,dest.open('wb') as dst:
     while True:
      block=src.read(1024*1024)
      if not block:break
      h.update(block);count+=len(block);dst.write(block)
    if count!=info['bytes'] or h.hexdigest()!=info['sha256']:raise ValueError('Source payload mismatch '+member.name)
    dest.chmod(member.mode&0o777);seen.add(member.name)
  if seen!=set(expected):raise ValueError('Source payload files missing')
  os.rename(parent/'external',target)
 finally:shutil.rmtree(parent,ignore_errors=True)
 print('Restored',len(seen),'audited actual source files; rebuild native targets before measurements')
if __name__=='__main__':main()

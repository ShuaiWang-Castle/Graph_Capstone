#!/usr/bin/env python3
"""Retrieve exact public source revisions from the recorded lock, no installers."""
from pathlib import Path
import json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
def run(args,cwd=None):
 print(' '.join(args),flush=True);subprocess.run(args,cwd=cwd,check=True)
def main():
 for source in json.loads((ROOT/'provenance/SOURCE_LOCK.json').read_text())['sources']:
  dest=ROOT/source['path'];url=source.get('url',source.get('git_url'));commit=source['commit']
  if (dest/'.git').exists():
   current=subprocess.check_output(['git','rev-parse','HEAD'],cwd=dest,text=True).strip()
   if current!=commit:raise RuntimeError(f'{dest} is a different revision; preserve it, choose a clean workspace')
   if subprocess.check_output(['git','diff','--name-only','HEAD'],cwd=dest,text=True).strip():raise RuntimeError(f'{dest} has source changes; do not reset')
   continue
  if dest.exists():raise RuntimeError(f'{dest} exists without Git metadata; do not overwrite it')
  dest.parent.mkdir(parents=True,exist_ok=True);run(['git','init',str(dest)]);run(['git','remote','add','origin',url],dest);run(['git','fetch','--depth','1','origin',commit],dest);run(['git','checkout','--detach','FETCH_HEAD'],dest)
if __name__=='__main__':main()

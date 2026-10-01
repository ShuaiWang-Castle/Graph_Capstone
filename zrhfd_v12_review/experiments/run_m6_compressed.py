"""Execute the unchanged frozen M6 cohort; compress only between queries."""
from pathlib import Path
import argparse,importlib.util,json,signal,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'experiments/m6_prepared'))
from experiments.apfs_storage import compress_terminal
spec=importlib.util.spec_from_file_location('frozen_m6_controller',ROOT/'experiments/m6_prepared/run.py')
controller=importlib.util.module_from_spec(spec);spec.loader.exec_module(controller)
original=controller.execute_child

def stored_child(request,directory,limits):
    try:record=original(request,directory,limits)
    except KeyboardInterrupt:
        if (Path(directory)/'terminal.json').exists():compress_terminal(directory)
        raise
    storage=compress_terminal(directory)
    print(json.dumps({'post_measurement_storage':str(Path(directory).relative_to(ROOT)),
        'allocated_before_bytes':storage['allocated_before_bytes'],
        'allocated_after_bytes':storage['allocated_after_bytes'],'all_original_bytes_unchanged':True}),flush=True)
    return record

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--run',action='store_true');ap.add_argument('--max-queries',type=int);args=ap.parse_args()
    if not args.run:raise SystemExit('Use --run to execute the frozen cohort')
    def stopping(signum,frame):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stopping)
    # Interrupted/failed prior attempts remain query statuses; storage never retries them.
    for terminal in sorted((ROOT/'results/m6_prepared/queries').glob('*/attempt_*/terminal.json')):
        if not (terminal.parent/'TRANSPARENT_STORAGE.json').exists():compress_terminal(terminal.parent)
    controller.execute_child=stored_child
    controller.run(args.max_queries,False)

"""Run the frozen M5 controller and losslessly archive each terminal attempt.

The original worker, method parameters, commands, budgets and measurement
receipts remain unchanged. The wrapper performs storage only after run_one
returns, including failed/time-limited attempts.
"""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.m5 import run_serial as frozen_controller
from experiments.archival import archive_completed_attempt

original_run_one=frozen_controller.run_one
def archived_run_one(directory,*args,**kwargs):
    try:receipt=original_run_one(directory,*args,**kwargs)
    except KeyboardInterrupt:
        if (Path(directory)/'receipt.json').exists():archive_completed_attempt(directory)
        raise
    metadata=archive_completed_attempt(directory)
    print(json.dumps({'post_measurement_storage':str(Path(directory).relative_to(ROOT)),
        'expanded_bytes':metadata['expanded_bytes'],'archive_bytes':metadata['archive_bytes'],
        'all_original_bytes_preserved':True}),flush=True)
    return receipt

if __name__=='__main__':
    # A prior controller can have finished a terminal receipt before storage.
    # Recover such attempts before launching the next measurement.
    args=sys.argv[1:];run=args[args.index('--run')+1] if '--run' in args else 'results/m5/official_v12_001'
    if '--execute' in args:
        for receipt in sorted((ROOT/run/'queries').glob('*/attempt_*/receipt.json')):
            if not (receipt.parent/'ARCHIVE.json').exists():archive_completed_attempt(receipt.parent)
    frozen_controller.run_one=archived_run_one
    frozen_controller.main()

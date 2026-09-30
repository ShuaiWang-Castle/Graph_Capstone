from __future__ import annotations
import unittest,tempfile,sys,json,subprocess,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lab.metrics import score
from lab.io import write_json,read_json,graph,cover,sha256
from lab.runner import run_job

class MetricsTests(unittest.TestCase):
    def test_perfect(self):
        x=score([{0,1,2},{2,3,4}],[{2,3,4},{0,1,2}],5)
        self.assertEqual(x['matched_macro_f1'],1);self.assertEqual(x['extra_membership_after_first']['recall'],1)
    def test_empty_prediction(self):
        x=score([{0,1}],[ ],3);self.assertEqual(x['matched_macro_f1'],0)
        self.assertEqual(x['matched_membership_micro']['f1'],0)
    def test_duplicate_penalty(self):
        x=score([{0,1}],[{0,1},{0,1}],2);self.assertAlmostEqual(x['matched_macro_f1'],2/3)
        self.assertEqual(x['duplicate_predicted_groups'],1)
    def test_missing_group(self):
        x=score([{0,1},{2,3}],[{0,1}],4)
        self.assertAlmostEqual(x['matched_macro_recall'],.5);self.assertAlmostEqual(x['matched_macro_f1'],2/3)
    def test_no_overlap_is_na(self):
        x=score([{0},{1}],[{0},{1}],2);self.assertIsNone(x['extra_membership_after_first']['recall'])
    def test_invalid_node(self):
        with self.assertRaises(ValueError):score([{0,1}],[{2}],2)
    def test_duplicate_truth_rejected(self):
        with self.assertRaises(ValueError):score([{0,1},{0,1}],[{0,1}],2)
    def test_same_node_relabelling(self):
        t=[{0,1,2},{2,3}];p=[{0,2},{1,2,3}];perm={0:3,1:2,2:1,3:0}
        x=score(t,p,4);y=score([{perm[i] for i in c} for c in t],[{perm[i] for i in c} for c in p],4)
        self.assertEqual(x['matched_macro_f1'],y['matched_macro_f1'])
    def test_false_overlap(self):
        x=score([{0,1},{2,3}],[{0,1,2},{2,3}],4)
        self.assertEqual(x['overlap_node']['precision'],0)
    def test_micro_count(self):
        x=score([{0,1,2},{2,3}],[{0,1},{2,3}],4)
        self.assertEqual(x['matched_membership_micro']['tp'],4)
        self.assertEqual(x['extra_membership_after_first']['recall'],0)

class IOTests(unittest.TestCase):
    def test_graph_and_hash(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'g.json';write_json(p,{'n':3,'edges':[[0,1]]})
            self.assertEqual(graph(p),(3,[(0,1)]));self.assertEqual(len(sha256(p)),64)
    def test_reversed_edge_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'g.json';write_json(p,{'n':3,'edges':[[1,0]]})
            with self.assertRaises(ValueError):graph(p)
    def test_duplicate_edge_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'g.json';write_json(p,{'n':3,'edges':[[0,1],[0,1]]})
            with self.assertRaises(ValueError):graph(p)
    def test_cover_preserves_group_duplicates(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'c.json';write_json(p,{'communities':[[0,0,1],[],[0,1]]})
            c,a=cover(p,3);self.assertEqual(len(c),2);self.assertEqual(a['duplicate_groups_retained'],1)
    def test_lfr_conversion(self):
        sys.path.insert(0,str(ROOT/'tools'));from generate_lfr import convert
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);(d/'network.dat').write_text('1 2\n2 1\n2 3\n3 2\n')
            (d/'community.dat').write_text('1 1\n2 1 2\n3 2\n')
            g,t,a=convert(d,3,1,2);self.assertEqual(len(g['edges']),2);self.assertEqual(a['overlap_nodes_observed'],1)
    def test_lfr_wrong_overlap_rejected(self):
        sys.path.insert(0,str(ROOT/'tools'));from generate_lfr import convert
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);(d/'network.dat').write_text('1 2\n2 1\n');(d/'community.dat').write_text('1 1\n2 1\n')
            with self.assertRaises(ValueError):convert(d,2,1,2)

class RunnerTests(unittest.TestCase):
    def spec(self,d,cmd):
        g=d/'g.json';c=d/'c.json';write_json(g,{'n':3,'edges':[[0,1]]});write_json(c,{})
        return {'job_id':'test','case_id':'test','method':'HARNESS_TEST','command':cmd,'graph':str(g),'config':str(c),
                'seed':1,'threads':1,'device':'cpu','timeout_s':10,'memory_mb':2048,'information_policy':'SMOKE_ONLY',
                'graph_sha256':sha256(g),'config_sha256':sha256(c)}
    def test_completion_and_resume(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);cmd=['{python}','{root}/adapters/run.py','--method','components_smoke','--graph','{graph}','--output','{output}','--seed','{seed}','--config','{config}']
            j=self.spec(d,cmd);r=run_job(j,ROOT,d/'runs');self.assertEqual(r['status'],'COMPLETED')
            self.assertEqual(r,run_job(j,ROOT,d/'runs'))
    def test_timeout(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);j=self.spec(d,['{python}','-c','import time; time.sleep(10)']);j['timeout_s']=1.1
            self.assertEqual(run_job(j,ROOT,d/'runs')['status'],'TIMEOUT')
    def test_error(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);j=self.spec(d,['{python}','-c','raise SystemExit(3)'])
            self.assertEqual(run_job(j,ROOT,d/'runs')['status'],'ERROR')
    def test_changed_hash_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);j=self.spec(d,['{python}','-c','pass']);write_json(j['graph'],{'n':2,'edges':[]})
            with self.assertRaises(ValueError):run_job(j,ROOT,d/'runs')
    def test_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);j=self.spec(d,['{python}','-c','pass']);j['blocked_reason']='test no download'
            self.assertEqual(run_job(j,ROOT,d/'runs')['status'],'BLOCKED')
    def test_exhausted(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);j=self.spec(d,['{python}','-c','pass'])
            self.assertEqual(run_job(j,ROOT,d/'runs',remaining_seconds=0)['status'],'NOT_RUN_BUDGET')
    def test_missing_output(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);j=self.spec(d,['{python}','-c','pass'])
            self.assertEqual(run_job(j,ROOT,d/'runs')['status'],'INVALID_OUTPUT')

if __name__=='__main__':unittest.main()

#!/usr/bin/env python3
"""Integration adapter for the AUTHOR PyTorch NOCD library, graph-only known-K.
Training loop follows the upstream notebook, with no ground-truth reads.
A device-neutral sparse-dropout compatibility patch is explicit in metadata.
Native dependency/API behavior is NOT tested by the bundled offline selftests.
"""
from __future__ import annotations
import argparse,sys,time,os,json,random,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from lab.io import read_json,write_json,graph,sha256

def main():
    t0=time.perf_counter();p=argparse.ArgumentParser()
    for x in ['graph','output','config']:p.add_argument('--'+x,required=True)
    p.add_argument('--seed',type=int,required=True);a=p.parse_args();cfg=read_json(a.config)
    import numpy as np
    import scipy.sparse as sp
    import torch
    import torch.nn.functional as functional
    from sklearn.preprocessing import normalize
    sys.path.insert(0,str(Path(cfg['source_dir']).resolve()))
    import nocd
    import nocd.nn.gcn as gcn_module
    from candidates.nocd_pairdot.pairdot import prepare_pairs,sparse_pair_dot,bmm_pair_dot,batch_loss_with_pair_dot
    backend=cfg['pairdot_backend']
    if backend not in ['elementwise','bmm','sampled_csr']:raise ValueError('Unregistered pairdot backend')
    if Path(cfg['module_path']).resolve()!=Path(__file__).with_name('pairdot.py').resolve():raise ValueError('Configured pairdot source differs')
    if cfg.get('device','cpu')!='cpu':raise ValueError('Only CPU pairdot configuration is registered')
    if backend!='elementwise':
        def dot(emb,pairs):
            if backend=='bmm':return bmm_pair_dot(emb,pairs)
            # Prepare every sampled batch inside measured training. No cached
            # preprocessing from a free worker or a different input graph.
            return sparse_pair_dot(emb,prepare_pairs(pairs,emb.shape[0]))
        def batch_loss(self,emb,ones,zeros):
            return batch_loss_with_pair_dot(self,emb,ones,zeros,dot)
        nocd.nn.BerpoDecoder.loss_batch=batch_loss
    random.seed(a.seed);np.random.seed(a.seed);torch.manual_seed(a.seed)
    device=torch.device(cfg.get('device','cpu'))
    if device.type=='cuda':torch.cuda.manual_seed_all(a.seed)
    torch.set_num_threads(int(cfg.get('threads',1)))
    def dropout(x,p=.5,training=True):
        if x.is_sparse:
            x=x.coalesce();v=functional.dropout(x.values(),p=p,training=training)
            return torch.sparse_coo_tensor(x.indices(),v,x.shape,device=x.device).coalesce()
        return functional.dropout(x,p=p,training=training)
    gcn_module.sparse_or_dense_dropout=dropout
    n,edges=graph(a.graph);m=len(edges);k=int(cfg['k'])
    if not 0<m<n*(n-1)//2:raise ValueError('NOCD BP decoder expects positive edge and nonedge counts; report unsupported empty/full graph')
    if k<1:raise ValueError('Known-K adapter needs a configured k; it never reads truth')
    e=np.asarray(edges,dtype=np.int64);rows=np.r_[e[:,0],e[:,1]];cols=np.r_[e[:,1],e[:,0]]
    adj=sp.csr_matrix((np.ones(2*m,dtype=np.float32),(rows,cols)),shape=(n,n))
    def tt(mat):
        mat=mat.tocoo();ids=torch.tensor(np.vstack((mat.row,mat.col)),dtype=torch.long,device=device)
        vals=torch.tensor(mat.data,dtype=torch.float32,device=device)
        return torch.sparse_coo_tensor(ids,vals,mat.shape,device=device).coalesce()
    x=tt(normalize(adj,norm='l2',axis=1))
    norm=adj+sp.eye(n,dtype=np.float32,format='csr');d=np.asarray(norm.sum(axis=1)).ravel();iv=1/np.sqrt(d)
    adj_norm=tt(norm.multiply(iv[:,None]).multiply(iv[None,:]))
    model=nocd.nn.GCN(n,cfg.get('hidden_sizes',[128]),k,dropout=float(cfg.get('dropout',.5)),batch_norm=bool(cfg.get('batch_norm',True))).to(device)
    decoder=nocd.nn.BerpoDecoder(n,adj.nnz,balance_loss=bool(cfg.get('balance_loss',True)))
    opt=torch.optim.Adam(model.parameters(),lr=float(cfg.get('lr',.001)))
    batch=int(cfg.get('batch_size',20000));max_epochs=int(cfg.get('max_epochs',500))
    sampler=nocd.sampler.EdgeSampler(adj,batch,batch)
    check=int(cfg.get('check_every',25));patience=int(cfg.get('patience_checks',10));best=float('inf');state=None;stale=0
    threshold=float(cfg.get('threshold',.5));trace=[];checkpoint=os.environ.get('LAB_CHECKPOINT')
    outdir=Path(a.output).parent;stage={'setup_seconds':time.perf_counter()-t0,'sample_seconds':0.,'full_evaluation_seconds':0.,'forward_loss_backward_seconds':0.,'optimizer_seconds':0.,'checkpoint_write_seconds':0.}
    def sync():
        if device.type=='cuda':torch.cuda.synchronize(device)
    def save_array(path,array):
        path=Path(path);temp=path.with_suffix(path.suffix+'.tmp')
        with temp.open('wb') as f:np.save(f,array,allow_pickle=False)
        os.replace(temp,path)
    def save_model(path,payload):
        path=Path(path);temp=path.with_suffix(path.suffix+'.tmp')
        torch.save(payload,temp);os.replace(temp,path)
    def snapshot(emb,path,kind):
        z=emb.detach().cpu().numpy();cs=[np.flatnonzero(z[:,i]>threshold).astype(int).tolist() for i in range(k)]
        write_json(path,{'communities':cs,'method':'NOCD-G-author-PyTorch-adapter','seed':a.seed,
          'metadata':{'known_k':k,'input_features':'row-l2-normalized adjacency only',
                      'selection':'minimum full TRAINING reconstruction loss at fixed check intervals; not heldout validation',
                      'kind':kind,'compatibility_patch':'device-neutral sparse dropout',
                      'sampler':'author EdgeSampler keyed by epoch; serial direct Dataset call; no labels',
                      'upstream_gcn_sha256':sha256(Path(cfg['source_dir'])/'nocd/nn/gcn.py'),
                      'candidate_mechanism':'C1 sampled-loss pairdot primitive only',
                      'pairdot_backend':backend,'pairdot_source_sha256':sha256(cfg['module_path']),
                      'full_loss_selection':'unchanged author loss_full',
                      'all_pair_preprocessing_in_pipeline':True,'new_algorithmic_principle':False},
          'stage_seconds':{**stage,'elapsed':time.perf_counter()-t0},'trace':trace})
    trainstart=time.perf_counter();termination='max_epochs'
    for epoch in range(max_epochs+1):
        if epoch%check==0 or epoch==max_epochs:
            phase=time.perf_counter()
            model.eval()
            with torch.no_grad():
                emb=functional.relu(model(x,adj_norm));loss=float(decoder.loss_full(emb,adj).item())
            sync();stage['full_evaluation_seconds']+=time.perf_counter()-phase
            trace.append({'epoch':epoch,'elapsed_seconds':time.perf_counter()-t0,'training_reconstruction_loss':loss})
            if not np.isfinite(loss):raise FloatingPointError('Nonfinite NOCD loss')
            if loss<best:
                best=loss;state=copy.deepcopy(model.state_dict());stale=0
                phase=time.perf_counter()
                if checkpoint:snapshot(emb,checkpoint,'partial_checkpoint')
                save_array(outdir/'best_embedding.npy',emb.detach().cpu().numpy())
                save_model(outdir/'best_model.pt',{'state_dict':state,'optimizer_state_dict':opt.state_dict(),'epoch':epoch,'training_loss':loss,'seed':a.seed})
                stage['checkpoint_write_seconds']+=time.perf_counter()-phase
            else:stale+=1
            phase=time.perf_counter();snapshot(emb,outdir/'checkpoints'/f'epoch_{epoch:04d}.json','measured_evaluation_checkpoint')
            if epoch==0:save_array(outdir/'initial_embedding.npy',emb.detach().cpu().numpy())
            stage['checkpoint_write_seconds']+=time.perf_counter()-phase
            print(json.dumps(trace[-1]),flush=True)
            if stale>patience:termination='training_loss_patience';break
        if time.perf_counter()-t0>float(os.environ.get('LAB_BUDGET_SECONDS','1e20'))-3:
            termination='internal_time_budget';break
        if cfg.get('stochastic_loss',True):
            phase=time.perf_counter();ones,zeros=sampler[epoch];ones=ones.to(device);zeros=zeros.to(device);stage['sample_seconds']+=time.perf_counter()-phase
        phase=time.perf_counter()
        model.train();opt.zero_grad();emb=functional.relu(model(x,adj_norm))
        loss=decoder.loss_batch(emb,ones,zeros) if cfg.get('stochastic_loss',True) else decoder.loss_full(emb,adj)
        loss=loss+nocd.utils.l2_reg_loss(model,scale=float(cfg.get('weight_decay',.01)))
        loss.backward();sync();stage['forward_loss_backward_seconds']+=time.perf_counter()-phase
        phase=time.perf_counter();opt.step();sync();stage['optimizer_seconds']+=time.perf_counter()-phase
    if state is None:raise RuntimeError('No finite checkpoint')
    model.load_state_dict(state);model.eval()
    with torch.no_grad():emb=functional.relu(model(x,adj_norm))
    sync();snapshot(emb,a.output,termination)
    # A program can finish its fixed budget and return a valid approximate cover;
    # metadata explicitly distinguishes this from convergence.
if __name__=='__main__':main()

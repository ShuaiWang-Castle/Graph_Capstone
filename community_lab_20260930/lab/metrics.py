"""Label-invariant one-to-one cover scoring.
Duplicates across predicted groups are retained and penalized. Missing nodes are
not silently assigned. Applicable only when truth memberships are complete.
"""
from __future__ import annotations
import numpy as np
from scipy.optimize import linear_sum_assignment

def ratio(a,b):return float(a/b) if b else None

def prf(tp,pred,true):
    return {'precision':ratio(tp,pred),'recall':ratio(tp,true),
            'f1':ratio(2*tp,pred+true),'tp':int(tp),'pred':int(pred),'true':int(true)}

def score(truth,pred,n):
    truth=[set(c) for c in truth if c];pred=[set(c) for c in pred if c]
    if not truth:raise ValueError('Empty truth is not a supervised recovery task')
    if any(type(v) is not int or v<0 or v>=n for c in truth+pred for v in c):raise ValueError('Node outside universe')
    if len({frozenset(c) for c in truth})!=len(truth):raise ValueError('Duplicate truth communities')
    a,b=len(truth),len(pred)
    if a*b>5_000_000:raise ValueError('Dense matcher size guard. Implement a separately validated sparse matcher for this scale.')
    sim=np.zeros((a,b));inter=np.zeros((a,b),dtype=np.int64)
    for i,t in enumerate(truth):
        for j,p in enumerate(pred):
            x=len(t&p);inter[i,j]=x;sim[i,j]=2*x/(len(t)+len(p))
    if b:
        ri,cj=linear_sum_assignment(-sim)
        pairs=list(zip(ri.tolist(),cj.tolist()))
    else:pairs=[]
    total=sum(sim[i,j] for i,j in pairs)
    tp=sum(int(inter[i,j]) for i,j in pairs)
    tcount=np.zeros(n,dtype=int);pcount=np.zeros(n,dtype=int);correct=np.zeros(n,dtype=int)
    for t in truth:tcount[list(t)]+=1
    for p in pred:pcount[list(p)]+=1
    matched=[];rec_by_true=[0.0]*a
    for i,j in pairs:
        common=truth[i]&pred[j]
        correct[list(common)]+=1
        rec_by_true[i]=float(sim[i,j])
        matched.append({'truth_index':i,'pred_index':j,'f1':float(sim[i,j]),'intersection':int(inter[i,j])})
    ov_true=tcount>=2;ov_pred=pcount>=2
    extras_correct=int(np.maximum(correct-1,0).sum())
    extra_pred=int(np.maximum(pcount-1,0).sum());extra_true=int(np.maximum(tcount-1,0).sum())
    sizes=np.array([len(t) for t in truth]);q25=float(np.quantile(sizes,.25));small=sizes<=q25
    return {
      'truth_groups':a,'predicted_groups':b,
      'matched_macro_precision':float(total/b) if b else 0.0,
      'matched_macro_recall':float(total/a),
      'matched_macro_f1':float(2*total/(a+b)),
      'matched_membership_micro':prf(tp,sum(map(len,pred)),sum(map(len,truth))),
      'overlap_node':prf(int((ov_true&ov_pred).sum()),int(ov_pred.sum()),int(ov_true.sum())),
      'extra_membership_after_first':prf(extras_correct,extra_pred,extra_true),
      'at_least_two_correct_recall':ratio(int(((correct>=2)&ov_true).sum()),int(ov_true.sum())),
      'small_group_mean_matched_f1':float(np.array(rec_by_true)[small].mean()),
      'small_group_size_cutoff':q25,
      'pred_node_coverage':float(np.mean(pcount>0)),
      'truth_node_coverage':float(np.mean(tcount>0)),
      'duplicate_predicted_groups':len(pred)-len({frozenset(c) for c in pred}),
      'matching':matched,
      'matching_note':'One assignment maximizes SUM of pairwise F1; it is reused for micro and extra-membership diagnostics, not reoptimized per metric.',
      'extra_note':'Memberships are unordered. Extra means correctly recovered memberships after the first, not a semantic rank-2 label.',
      'onmi':None,'onmi_status':'Not implemented here; use a pinned, separately tested overlapping-NMI implementation, never sklearn partition NMI.'}

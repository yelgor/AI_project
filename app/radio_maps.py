"""Sparse radio maps. GPR is provided by scikit-learn; no propagation solver here."""
import math
import warnings
import numpy as np
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern
from sklearn.exceptions import ConvergenceWarning

METHODS = ('B0', 'B1', 'IDW', 'GPR-zero', 'GPR-pathloss')


class RadioMap:
    def __init__(self, method, transmitter, noise_db=2., optimize=False):
        if method not in METHODS: raise ValueError('Unknown radio map method')
        self.method=method; self.tx=np.asarray(transmitter,dtype=float)
        self.noise=float(noise_db); self.optimize=optimize; self.x=None; self.y=None; self.gp=None
        self.prior=np.array([0.,0.]); self.training_indices=[]

    def trend(self, points):
        distance=np.maximum(.1,np.linalg.norm(np.asarray(points)-self.tx,axis=1))
        return np.column_stack([np.ones(len(distance)),np.log10(distance)])

    def fit(self, observations):
        # Keep up to 150 recent spatially distinct points; stationary repeats do not dominate.
        chosen=[];positions=np.asarray([row['position_m'] for row in observations],dtype=float).reshape(-1,3)
        for i in reversed(range(len(observations))):
            row=observations[i]; value=row.get('rssi_dbm')
            if value is None or not math.isfinite(value): continue
            point=positions[i]
            if chosen:
                offsets=positions[chosen]-point
                if np.any(np.einsum('ij,ij->i',offsets,offsets)<.15**2):continue
            chosen.append(i)
            if len(chosen)>=150: break
        self.training_indices=sorted(chosen)
        self.x=np.asarray([observations[i]['position_m'] for i in self.training_indices],dtype=float).reshape(-1,3)
        self.y=np.asarray([observations[i]['rssi_dbm'] for i in self.training_indices],dtype=float)
        if not len(self.x): return self
        residual=self.y.copy()
        if self.method=='GPR-pathloss':
            if len(self.x)>=3 and np.ptp(self.trend(self.x)[:,1])>.05:
                self.prior=np.linalg.lstsq(self.trend(self.x),self.y,rcond=None)[0]
            else:
                self.prior=np.array([float(np.mean(self.y)),0.])
            residual-=self.trend(self.x)@self.prior
        if self.method.startswith('GPR'):
            kernel=ConstantKernel(1600.,(1.,10000.))*Matern(length_scale=2.,length_scale_bounds=(.2,30.),nu=1.5)
            self.gp=GaussianProcessRegressor(kernel=kernel,alpha=self.noise**2,normalize_y=False,
                optimizer='fmin_l_bfgs_b' if self.optimize else None,random_state=0)
            with warnings.catch_warnings():
                warnings.simplefilter('ignore',ConvergenceWarning); self.gp.fit(self.x,residual)
        return self

    def predict(self, points):
        p=np.asarray(points,dtype=float).reshape(-1,3)
        if self.x is None or not len(self.x): return [None]*len(p),[None]*len(p)
        if self.gp is not None:
            mean,std=self.gp.predict(p,return_std=True)
            if self.method=='GPR-pathloss': mean+=self.trend(p)@self.prior
            return mean.tolist(),std.tolist()
        distance=np.linalg.norm(p[:,None,:]-self.x[None,:,:],axis=2)
        weights=1/np.maximum(distance,.00001)**2
        mean=(weights@self.y)/weights.sum(axis=1)
        for i in range(len(p)):
            exact=distance[i]<1e-6
            if exact.any(): mean[i]=self.y[exact].mean()
        return mean.tolist(),[None]*len(p)

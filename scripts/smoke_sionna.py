import mitsuba as mi
mi.set_variant('llvm_ad_mono_polarized')
from sionna.rt import load_scene, scene, PlanarArray, Transmitter, Receiver, PathSolver
import numpy as np
world=load_scene(scene.box)
world.tx_array=PlanarArray(num_rows=1,num_cols=1,vertical_spacing=.5,horizontal_spacing=.5,pattern='iso',polarization='V')
world.rx_array=world.tx_array
world.add(Transmitter(name='tx',position=[-10,0,2]))
world.add(Receiver(name='rx',position=[-10,10,2]))
paths=PathSolver()(world,max_depth=3,samples_per_src=10000,max_num_paths_per_src=10000,diffraction=True,edge_diffraction=True,seed=42)
a,tau=paths.cir(out_type='numpy')
assert np.isfinite(a).all()
assert np.any(np.abs(a)>0), 'No propagation paths'
print('Sionna RT CPU: valid CIR; shape',a.shape,'nonzero',np.count_nonzero(a),'delay shape',tau.shape)

""" Gravitational Wave Surrogate classes for text and hdf5 files"""

from __future__ import division

__copyright__ = "Copyright (C) 2014 Scott Field and Chad Galley"
__email__     = "sfield@astro.cornell.edu, crgalley@tapir.caltech.edu"
__status__    = "testing"
__author__    = "Scott Field, Chad Galley"

__license__ = """
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

import numpy as np
from scipy.interpolate import splrep
from scipy.interpolate import splev
from harmonics import sYlm as sYlm
import const_mks as mks
import gwtools
import matplotlib.pyplot as plt
import time
import os as os
from parametric_funcs import function_dict as my_funcs
from surrogateIO import TextSurrogateRead, TextSurrogateWrite

try:
	import h5py
	h5py_enabled = True
except ImportError:
	h5py_enabled = False


# needed to search for single mode surrogate directories 
def list_folders(path,prefix):
        '''returns all folders which begin with some prefix'''
        for f in os.listdir(path):
                if f.startswith(prefix):
                        yield f

# handy helper to save waveforms 
def write_waveform(t, hp, hc, filename='output',ext='bin'):
  """write waveform to text or numpy binary file"""

  if( ext == 'txt'):
    np.savetxt(filename, [t, hp, hc])
  elif( ext == 'bin'):
    np.save(filename, [t, hp, hc])
  else:
    raise ValueError('not a valid file extension')


##############################################
class ExportSurrogate(H5Surrogate, TextSurrogateWrite):
	"""Export single-mode surrogate"""
	
	#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
	def __init__(self, path):
		
		# export HDF5 or Text surrogate data depending on input file extension
		ext = path.split('.')[-1]
		if ext == 'hdf5' or ext == 'h5':
			H5Surrogate.__init__(self, file=path, mode='w')
		else:
			raise ValueError('use TextSurrogateWrite instead')


##############################################
class EvaluateSingleModeSurrogate(H5Surrogate, TextSurrogateRead):
  """Evaluate single-mode surrogate in terms of the waveforms' amplitude and phase"""

  #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  def __init__(self, path, deg=3):

    # Load HDF5 or Text surrogate data depending on input file extension
    ext = path.split('.')[-1]
    if ext == 'hdf5' or ext == 'h5':
      H5Surrogate.__init__(self, file=path, mode='r')
    else:
      TextSurrogateRead.__init__(self, path)
		
    # Interpolate columns of the empirical interpolant operator, B, using cubic spline
    if self.surrogate_mode_type  == 'waveform_basis':
      self.reB_spline_params = [splrep(self.times, self.B[:,jj].real, k=deg) for jj in range(self.dim_rb)]
      self.imB_spline_params = [splrep(self.times, self.B[:,jj].imag, k=deg) for jj in range(self.dim_rb)]
    elif self.surrogate_mode_type  == 'amp_phase_basis':
      self.B1_spline_params = [splrep(self.times, self.B_1[:,jj], k=deg) for jj in range(self.B_1.shape[1])]
      self.B2_spline_params = [splrep(self.times, self.B_2[:,jj], k=deg) for jj in range(self.B_2.shape[1])]
    else:
      raise ValueError('invalid surrogate type')

    # Convenience for plotting purposes
    self.plt = plt
		
    pass

  #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  def __call__(self, q, M=None, dist=None, phi_ref=None, f_low=None, samples=None):
    """Return surrogate evaluation for...

       Input
       =====
       q         --- mass ratio (dimensionless) 
       M         --- total mass (solar masses) 
       dist      --- distance to binary system (megaparsecs)
       phir      --- mode's phase at peak amplitude
       flow      --- instantaneous initial frequency, will check if flow_surrogate < flow 


       More information
       ================
       This routine evaluates gravitational wave complex polarization modes h_{ell m}
       defined on a sphere whose origin is the binary's center of mass. """

    # TODO: mode description here and point to paper with equation

    ### compute surrogate's parameter values from input ones (q,M) ###
    # Ex: symmetric mass ratio x = q / (1+q)^2 might parameterize the surrogate
    x = self.get_surr_params(q)

    # TODO: because samples is passed to _h_sur => it MUST be in dimensions t/M to make sense

    ### evaluate rh/M surrogate. Physical surrogates are generated by applying additional operations. ###
    hp, hc = self._h_sur(x, samples=samples)

    ### adjust phase if requested -- see routine for assumptions about mode's peak ###
    if (phi_ref is not None):
      h  = self.adjust_merger_phase(hp + 1.0j*hc,phi_ref)
      hp = h.real
      hc = h.imag

    ### if (q,M,distance) requested, use scalings and norm fit to get a physical mode ###
    if( M is not None and dist is not None):
      amp0    = ((M * mks.Msun ) / (dist * mks.Mpcinm )) * ( mks.G / np.power(mks.c,2.0) )
      t_scale = mks.Msuninsec * M
    else:
      amp0    = 1.0
      t_scale = 1.0

    hp     = amp0 * hp
    hc     = amp0 * hc

    ### t = input times or times at which surrogate was built ###
    if (samples is not None):
      t = samples
    else:
      t = self.time()

    t = t_scale * t

    ### check that surrogate's starting frequency is below f_low, otherwise throw a warning ###
    if f_low is not None:
      self.find_instant_freq(hp, hc, t, f_low)

    return t, hp, hc


  #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  def find_instant_freq(self, hp, hc, t, f_low = None):
    """instantaneous frequency at t_start for 

          h = A(t) exp(2 * pi * i * f(t) * t), 

       where \partial_t A ~ \partial_t f ~ 0. If f_low passed will check its been achieved."""

    f_instant = gwtools.find_instant_freq(hp, hc, t)

    if f_low is None:
      return f_instant
    else:
      if f_instant > f_low:
        raise Warning, "starting frequency is "+str(f_instant)
      else:
        pass


  #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  def amp_phase(self,h):
    """Get amplitude and phase of waveform, h = A*exp(i*phi)"""
    return gwtools.amp_phase(h)


  #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  def phi_merger(self,h):
    """Phase of mode (typically 22) at amplitude's discrete peak. h = A*exp(i*phi)."""

    amp, phase = self.amp_phase(h)
    argmax_amp = np.argmax(amp)

    return phase[argmax_amp]


  #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  def adjust_merger_phase(self,h,phiref):
    """Modify GW mode's phase such that at time of amplitude peak, t_peak, we have phase(t_peak) = phiref"""

    phimerger = self.phi_merger(h)
    phiadj    = phiref - phimerger

    return gwtools.modify_phase(h,phiadj)


  #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  def timer(self,M_eval=None,dist_eval=None,phi_ref=None,f_low=None,samples=None):
    """average time to evaluate surrogate waveforms. """

    qmin, qmax = self.fit_interval
    ran = np.random.uniform(qmin, qmax, 1000)

    tic = time.time()
    if M_eval is None:
      for i in ran:
        hp, hc = self._h_sur(i)
    else:
      for i in ran:
        t, hp, hc = self.__call__(i,M_eval,dist_eval,phi_ref,f_low,samples)

    toc = time.time()
    print 'Timing results (results quoted in seconds)...'
    print 'Total time to generate 1000 waveforms = ',toc-tic
    print 'Average time to generate a single waveform = ', (toc-tic)/1000.0
    pass

	
  #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  #TODO: this routine might not serve a useful purpose -- think about it
  def time(self, units=None):
    # NOTE: Is Mtot the total mass of the surrogate or the total mass one wants to evaluate the time?
    """Return time samples in specified units.
		
		Options for units:
		====================
		None		-- Time in geometric units, G=c=1 (DEFAULT)
		'solarmass' -- Time in units of solar masses
		'sec'		-- Time in units of seconds """

    t = self.times
    if units == 'solarmass':
      t *= mks.Msuninsec
    elif units == 'sec':
      t *= mks.Msuninsec
    return t

	
  #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  def basis(self, i, flavor='waveform'):
    """compute the ith cardinal, orthogonal, or waveform basis."""

    # TODO: need to gaurd against missing V,R and their relationships to B (or B_1, B_2)

    if flavor == 'cardinal':
      basis = self.B[:,i]
    elif flavor == 'orthogonal':
      basis = np.dot(self.B,self.V)[:,i]
    elif flavor == 'waveform':
      E = np.dot(self.B,self.V)
      basis = np.dot(E,self.R)[:,i]
    else:
      raise ValueError("Not a valid basis type")

    return basis


  #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  def resample_B(self, samples):
    """resample the empirical interpolant operator, B, at the input samples"""
    return np.array([splev(samples, self.reB_spline_params[jj])  \
             + 1j*splev(samples, self.imB_spline_params[jj]) for jj in range(self.dim_rb)]).T


  #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  def plot_pretty(self, time, hp, hc, fignum=1, flavor='regular'):
    """create a waveform figure with nice formatting and labels.
       returns figure method for saving, plotting, etc."""
    return gwtools.plot_pretty(time, hp, hc, fignum, flavor)

	
  #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  def plot_rb(self, i, showQ=True):
    """plot the ith reduced basis waveform"""

    # NOTE: Need to allow for different time units for plotting and labeling

    # Compute surrogate approximation of RB waveform
    basis = self.basis(i)
    hp    = basis.real
    hc    = basis.imag
		
    # Plot waveform
    fig = self.plot_pretty(self.times,hp,hc)

    if showQ:
      self.plt.show()
		
    # Return figure method to allow for saving plot with fig.savefig
    return fig
	

  #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  def plot_sur(self, q_eval, timeM=False, showQ=True):
    """plot surrogate evaluated at mass ratio q_eval"""

    t, hp, hc = self.__call__(q_eval)

    if self.t_units == 'TOverMtot':
      xlab = 'Time, $t/M$'
    else:
      xlab = 'Time, $t$ (sec)'

    # Plot surrogate waveform
    fig = self.plot_pretty(t,hp,hc)
    self.plt.xlabel(xlab)
    self.plt.ylabel('Surrogate waveform')
		
    if showQ:
      self.plt.show()
		
    # Return figure method to allow for saving plot with fig.savefig
    return fig
	

  #### below here are "private" member functions ###
  # These routine's evaluate a "bare" surrogate, and should only be called
  # by the __call__ method 
  #
  # These routine's use x as the parameter, which could be mass ratio,
  # symmetric mass ratio, or something else. Parameterization info should
  # be supplied by surrogate's parameterization tag.

  #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  def _affine_mapper_checker(self, x):
    """map parameter value x to the standard interval [-1,1] if necessary. 
       Check if x within training interval."""

    x_min, x_max = self.fit_interval

    if( x < x_min or x > x_max):
      print "Warning: Surrogate not trained at requested parameter value" # needed to display in ipython notebook
      Warning("Surrogate not trained at requested parameter value")


    # TODO: should be rolled like amp/phase/fit funcs
    if self.affine_map == 'minus1_to_1':
      x_0 = 2.*(x - x_min)/(x_max - x_min) - 1.;
    elif self.affine_map == 'zero_to_1':
      x_0 = (x - x_min)/(x_max - x_min);
    elif self.affine_map == 'none':
      x_0 = x
    else:
      raise ValueError('unknown affine map')
    return x_0

  #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  def _norm_eval(self, x_0, affine_mapped=True):
    """evaluate norm fit at x_0"""

    if not self.norms:
      return 1.

    # TODO: this seems hacky -- just so when calling from outside class (which shouldn't be done) it will evaluate correctly
    # TODO: need to gaurd against missing norm info
    if( not(affine_mapped) ):
      x_0 = self._affine_mapper_checker(x_0)

    nrm_eval  = np.array([ self.norm_fit_func(self.fitparams_norm, x_0) ])
    return nrm_eval


  #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  def _amp_eval(self, x_0):
    """evaluate amplitude fit at x_0"""
    # 0:self.dim_rb... could be bad: fit degrees of freedom have nothing to do with rb dimension
    #return np.array([ self.amp_fit_func(self.fitparams_amp[jj, 0:self.dim_rb], x_0) for jj in range(self.dim_rb) ])
    #return np.array([ self.amp_fit_func(self.fitparams_amp[jj,:], x_0) for jj in range(self.dim_rb) ])
    # TODO: How slow is shape?
    return np.array([ self.amp_fit_func(self.fitparams_amp[jj,:], x_0) for jj in range(self.fitparams_amp.shape[0]) ])


  #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  def _phase_eval(self, x_0):
    """evaluate phase fit at x_0"""
    #return np.array([ self.phase_fit_func(self.fitparams_phase[jj, 0:self.dim_rb], x_0) for jj in range(self.dim_rb) ])
    #return np.array([ self.phase_fit_func(self.fitparams_phase[jj,:], x_0) for jj in range(self.dim_rb) ])
    return np.array([ self.phase_fit_func(self.fitparams_phase[jj,:], x_0) for jj in range(self.fitparams_phase.shape[0]) ])


  #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  def _h_sur(self, x, samples=None):
    """Evaluate surrogate at parameter value x. x could be mass ratio, symmetric
       mass ratio or something else -- it depends on the surrogate's parameterization. 

       Returns dimensionless rh/M waveforms in units of t/M.

       This should ONLY be called by the __call__ method which accounts for 
       different parameterization choices. """

    ### Map q to the standard interval and check parameter validity ###
    x_0 = self._affine_mapper_checker(x)

    ### Evaluate amp/phase/norm fits ###
    amp_eval   = self._amp_eval(x_0)
    phase_eval = self._phase_eval(x_0)
    nrm_eval   = self._norm_eval(x_0)

    if self.surrogate_mode_type  == 'waveform_basis':

      ### Build dim_RB-vector fit evaluation of h ###
      h_EIM = amp_eval*np.exp(1j*phase_eval)
		
      if samples == None:
        surrogate = np.dot(self.B, h_EIM)
      else:
        surrogate = np.dot(self.resample_B(samples), h_EIM)


    elif self.surrogate_mode_type  == 'amp_phase_basis':

      if samples == None:
        sur_A = np.dot(self.B_1, amp_eval)
        sur_P = np.dot(self.B_2, phase_eval)
      else:
        sur_A = np.dot(np.array([splev(samples, self.B1_spline_params[jj]) for jj in range(self.B_1.shape[1])]).T, amp_eval)
        sur_P = np.dot(np.array([splev(samples, self.B2_spline_params[jj]) for jj in range(self.B_2.shape[1])]).T, phase_eval)

      surrogate = sur_A*np.exp(1j*sur_P)


    else:
      raise ValueError('invalid surrogate type')


    surrogate = nrm_eval * surrogate
    hp = surrogate.real
    #hp = hp.reshape([self.time_samples,])
    hc = surrogate.imag
    #hc = hc.reshape([self.time_samples,])

    return hp, hc


##############################################
class EvaluateSurrogate(EvaluateSingleModeSurrogate): 
# TODO: inherated from EvalSingleModeSurrogate to gain access to some functions. this should be better structured
  """Evaluate multi-mode surrogates"""

  #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  def __init__(self, path, deg=3):


    # Convenience for plotting purposes
    self.plt = plt

    ### fill up dictionary with single mode surrogate class ###
    self.single_modes = dict()

    # Load HDF5 or Text surrogate data depending on input file extension
    ext = path.split('.')[-1]
    if ext == 'hdf5' or ext == 'h5':
      raise ValueError('Not coded yet')
    else:
      ### compile list of available modes ###
      # assumes (i) single mode folder format l#_m#_ (ii) ell<=9, m>=0
      for single_mode in list_folders(path,'l'):
        mode_key = single_mode[0:5]
        print "loading surrogate mode... "+mode_key
        self.single_modes[mode_key] = EvaluateSingleModeSurrogate(path+single_mode+'/')

    ### Assumes all modes are defined on the same temporal grid. ###
    ### TODO: should explicitly check this in previous step ###
    self.time_all_modes = self.single_modes[mode_key].time

  #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  def __call__(self, q, M=None, dist=None, theta=None,phi=None,phi_ref=None, f_low=None, samples=None, ell=None, m=None, mode_sum=True):
    """Return surrogate evaluation for...

      q    = mass ratio (dimensionless) 
      M    = total mass (solar masses) 
      dist  = distance to binary system (megaparsecs)
      theta/phi --- evaluate hp and hc modes at this location on sphere
      phir = mode's phase at peak amplitude
      flow = instantaneous initial frequency, will check if flow_surrogate < flow 
      ell = list or array of N ell modes to evaluate for (if none, all modes are returned)
      m   = for each ell, supply a matching m value 
      mode_sum = if true, all modes are summed, if false all modes are returned in an array

      NOTE: if only requesting one mode, this should be ell=[2],m=[2]

       Note about Angles
       =================
       For circular orbits, the binary's orbital angular momentum is taken to
       be the z-axis. Theta and phi is location on the sphere relative to this 
       coordiante system. """

    # TODO: automatically generate m<0 too, control with flag

    ### deduce single mode dictionary keys from ell,m input ###
    eval_mode_keys  = self.generate_mode_keys(ell,m)
 
    ### allocate arrays for multimode polarizations ###
    if mode_sum:
      hp_full, hc_full = self.allocate_output_array(samples,1)
    else:
      hp_full, hc_full = self.allocate_output_array(samples,len(eval_mode_keys))

    ii = 0
    for mode_key in eval_mode_keys:

      ell = mode_key[1]
      m   = mode_key[4]

      t_mode, hp_mode, hc_mode = self.evaluate_single_mode(q,M,dist,phi_ref,f_low,samples,mode_key,ell,m)
      hp_mode, hc_mode         = self.evaluate_on_sphere(ell,m,theta,phi,hp_mode,hc_mode)

      if mode_sum:
        hp_full = hp_full + hp_mode
        hc_full = hc_full + hc_mode
      else:
        hp_full[:,ii] = hp_mode[:]
        hc_full[:,ii] = hc_mode[:]


      ii+=1

    return t_mode, hp_full, hc_full #assumes all mode's have same temporal gride


  #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  def evaluate_on_sphere(self,ell,m,theta,phi,hp_mode,hc_mode):
    """elvaluate on the sphere"""

    if( theta is not None and phi is not None):
      sYlm_value =  sYlm(-2,ll=ell,mm=m,theta=theta,phi=phi)
      hp_mode = sYlm_value*hp_mode
      hc_mode = 1.0j*sYlm_value*hc_mode

    return hp_mode, hc_mode

  #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  def evaluate_single_mode(self,q, M, dist, phi_ref, f_low, samples,mode_key,ell,m):
    """ light wrapper around single mode evaluator to account for m < 0 modes """

    t_mode, hp_mode, hc_mode = self.single_modes[mode_key](q, M, dist, phi_ref, f_low, samples)
    if m < 0: # h(l,-m) = (-1)^l h(l,m)^* (TODO: CHECK THESE EXPRESSIONS AGAINST SPEC OR LAL OUTPUT)
      hp_mode =   np.power(-1,ell) * hp_mode
      hc_mode = - np.power(-1,ell) * hc_mode

    return t_mode, hp_mode, hc_mode


  #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  def allocate_output_array(self,samples,num_modes):
    """ allocate memory for result of hp, hc.

    Input
    =====
    samples   --- array of time samples. None if using default
    num_modes --- number of harmonic modes (cols). set to 1 if summation over modes"""

    if (samples is not None):
      hp_full = np.zeros((samples.shape[0],num_modes))
      hc_full = np.zeros((samples.shape[0],num_modes))
    else:
      hp_full = np.zeros((self.time_all_modes().shape[0],num_modes))
      hc_full = np.zeros((self.time_all_modes().shape[0],num_modes))

    if( num_modes == 1): #TODO: hack to prevent broadcast when summing over modes
      hp_full = hp_full.reshape([hp_full.shape[0],])
      hc_full = hp_full.reshape([hp_full.shape[0],])

    return hp_full, hc_full

  #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  def generate_mode_keys(self,ell=None,m=None):
    """from list of [ell],[m] pairs, generate mode keys to evaluate for """

    if ell is None: # evaluate for all available modes
      mode_keys = self.single_modes.keys()
    else:
      modes = [(x, y) for x in ell for y in m] 
      mode_keys = []
      for ell,m in modes:
        if m>=0:
          mode_key = 'l'+str(ell)+'_m'+str(m)
        else:
          mode_key = 'l'+str(ell)+'_m'+str(int(-m))

      mode_keys.append(mode_key)

    return mode_keys


####################################################
def CompareSingleModeSurrogate(sur1,sur2):
  """ Compare data defining two surrogates"""

  #TODO: should loop over necessary and optional data fields in future SurrogateIO class

  for key in sur1.__dict__.keys():

    if key in ['B','V','R','fitparams_phase','fitparams_amp',\
               'fitparams_norm','greedy_points','eim_indices']:

      if np.max(np.abs(sur1.__dict__[key] - sur2.__dict__[key])) != 0:
        print "checking attribute "+str(key)+"...DIFFERENT!!!"
      else:
        print "checking attribute "+str(key)+"...agrees"

    elif key in ['fit_type_phase','fit_type_amp','fit_type_norm']:

      if sur1.__dict__[key] == sur2.__dict__[key]:
        print "checking attribute "+str(key)+"...agrees"
      else:
         print "checking attribute "+str(key)+"...DIFFERENT!!!"

    else:
      print "not checking attribute "+str(key)




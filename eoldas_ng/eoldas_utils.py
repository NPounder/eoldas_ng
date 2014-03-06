#!/usr/bin/env python
"""
EOLDAS ng utililty functions
================================

A number of functions to deal with GP emulators etc that
are required for the EOLDAS opereators
"""

__author__  = "J Gomez-Dans"
__version__ = "1.0 (1.12.2013)"
__email__   = "j.gomez-dans@ucl.ac.uk"

import numpy as np
import scipy.ndimage.interpolation

from gp_emulator import GaussianProcess

def create_inverse_emulators ( original_emulator, band_pass, state_config ):
    """
    This function takes a multivariable output trained emulator
    and "retrains it" to take input reflectances and report a
    prediction of single input parameters (i.e., regression from
    reflectance/radiance to state). This is a useful starting 
    point for spatial problems.
    
    Parameters
    ------------
    original_emulator: emulator
        An emulator (type gp_emulator.GaussianProcess)
    band_pass: array
        A 2d bandpass array (nbands, nfreq). Logical type
    state_config: ordered dict
        A state configuration ordered dictionary.
    """
    
    # For simplicity, let's get the training data out of the emulator
    X = original_emulator.X_train*1.
    y = original_emulator.y_train*1.
    # Apply band pass functions here...
    n_bands = band_pass.shape[0]
    xx = np.array( [ X[:, band_pass[i,:]].sum(axis=1)/ \
        (1.*band_pass[i,:].sum()) \
        for i in xrange( n_bands ) ] )

    # A container to store the emulators
    gps = {}
    for  i, (param, typo) in enumerate ( state_config.iteritems()) :
        if typo == VARIABLE:
            gp = GaussianProcess ( xx.T, y[:, i] )
            gp.learn_hyperparameters( n_tries = 3 )
            gps[param] = gp 
    return gps
    
def perband_emulators ( emulators, band_pass ):
    """This function creates per band emulators from the full-spectrum
    emulator. Should be faster in many cases"""
    
    n_bands = band_pass.shape[0]
    x_train_pband = [ emulators.X_train[:,band_pass[i,:]].mean(axis=1) \
        for i in xrange( n_bands ) ]
    x_train_pband = np.array ( x_train_pband )
    emulators = []
    for i in xrange( n_bands ):
        gp = GaussianProcess ( emulators.y_train[:75]*1, \
                x_train_pband[i,:75] )
        gp.learn_hyperparameters ( n_tries=3 )
        emulators.append ( gp )
    return emulators

def get_problem_size ( x_dict, state_config ):
    """This function reports
    1. The number of parameters `n_params`
    2. The size of the state

    Parameters
    -----------
    x_dict: dict
        An (ordered) dictionary with the state
    state_config: dict
        A state configuration ordered dictionary
    """
    n_params = 0
    for param, typo in state_config.iteritems():
        if typo == CONSTANT:
            n_params += 1
        elif typo == VARIABLE:
            n_elems = x_dict[param].size
            n_params += n_elems
    return n_params, n_elems

def test_fwd_model ( x, the_emu, obs, bu, band_pass, bw):
    f,g = fwd_model ( the_emu, x, obs, bu, band_pass, bw )
    return f#,g.sum(axis=0)

def der_test_fwd_model ( x, the_emu, obs, bu, band_pass, bw):
    f,g = fwd_model ( the_emu, x, obs, bu, band_pass, bw )
    return g


def fwd_model ( gp, x, R, band_unc, band_pass, bw ):
    """
    A generic forward model using GPs. We pass the gp object as `gp`,
    the value of the state as `x`, the observations as `R`, observational
    uncertainties per band as `band_unc`, and spectral properties of 
    bands as `band_pass` and `bw`.
    
    Returns
    -------
    
    The cost associated with x, and the partial derivatives.
    
    """
    f, g = gp.predict ( np.atleast_2d( x ) )
    cost = 0
    der_cost = []
    
    for i in xrange( len(band_pass) ):
        d = f[band_pass[i]].sum()/bw[i] - R[i]
        #derivs = d*g[:, band_pass[i] ]/(bw[i]*(band_unc[i]**2))
        derivs = d*g[:, band_pass[i] ]/((band_unc[i]**2))
        cost += 0.5*np.sum(d*d)/(band_unc[i])**2
        der_cost.append ( np.array(derivs.sum( axis=1)).squeeze() )
    return cost, np.array( der_cost ).squeeze().sum(axis=0)

def downsample(myarr,factorx,factory):
    """
    Downsample a 2D array by averaging over *factor* pixels in each axis.
    Crops upper edge if the shape is not a multiple of factor.

    This code is pure numpy and should be fast.
    Leeched from <https://code.google.com/p/agpy/source/browse/trunk/agpy/downsample.py?r=114>
    """
    xs,ys = myarr.shape
    crarr = myarr[:xs-(xs % int(factorx)),:ys-(ys % int(factory))]
    dsarr = np.concatenate([[crarr[i::factorx,j::factory] 
        for i in range(factorx)] 
        for j in range(factory)]).mean(axis=0)
    return dsarr

def fit_smoothness (  x, sigma_model  ):
    """
    This function calculates the spatial smoothness constraint. We use
    a numpy strides trick to efficiently evaluate the neighbours. Note
    that there are no edges here, we just ignore the first and last
    rows and columns. Also note that we could have different weights
    for x and y smoothing (indeed, diagonal smoothing) quite simply
    """
    # Build up the 8-neighbours
    hood = np.array ( [  x[:-2, :-2], x[:-2, 1:-1], x[ :-2, 2: ], \
                    x[ 1:-1,:-2], x[1:-1, 2:], \
                    x[ 2:,:-2], x[ 2:, 1:-1], x[ 2:, 2:] ] )
    j_model = 0
    der_j_model = x*0
    for i in [1,3,4,6]:#range(8):
        j_model = j_model + 0.5*np.sum ( ( hood[i,:,:] - \
      x[1:-1,1:-1] )**2 )/sigma_model**2
        der_j_model[1:-1,1:-1] = der_j_model[1:-1,1:-1] - \
      ( hood[i,:,:] - x[1:-1,1:-1] )/sigma_model**2
    return ( j_model, 2*der_j_model )

def fit_observations_gauss ( x, obs, sigma_obs, qa, factor=1 ):
    """
    A fit to the observations term. This function returns the likelihood

    
    """
    if factor == 1:
        der_j_obs = np.where ( qa == 1, (x - obs)/sigma_obs**2, 0 )
        j_obs = np.where ( qa  == 1, 0.5*(x - obs)**2/sigma_obs**2, 0 )
        j_obs = j_obs.sum()
    else:
        j_obs, der_j_obs = fit_obs_spat ( x, obs, sigma_obs, qa, factor )

    return ( j_obs, der_j_obs )

  
def fit_obs_spat ( x, obs, sigma_obs, qa, factor ):
    """
    A fit to the observations term. This function returns the likelihood

    
    """
    
    xa = downsample ( x, factor[0], factor[1] )
    
    assert ( xa.shape == obs.shape )
    der_j_obs = np.where ( qa == 1, (xa - obs)/sigma_obs**2, 0 )
    
    der_j_obs = scipy.ndimage.interpolation.zoom ( der_j_obs, factor, order=1 )
    j_obs = np.where ( qa == 1, 0.5*(xa - obs)**2/sigma_obs**2, 0 )
    j_obs = j_obs.sum()
    return ( j_obs, der_j_obs )
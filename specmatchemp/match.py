"""
@filename match.py

Defines the Match class
"""
import pandas as pd
import numpy as np
import lmfit
from scipy.interpolate import UnivariateSpline
import scipy.ndimage as nd

import specmatchemp.kernels

class Match:
    def __init__(self, target, reference):
        """
        The Match class used for matching two spectra

        target, reference spectra should be given as Pandas dataframes.
        """
        target.columns = ['s_targ', 'serr_targ', 'w']
        reference.columns = ['s_ref', 'serr_ref', 'w']
        self.spectra = pd.merge(target, reference, how='inner', on='w')
        self.best_params = lmfit.Parameters()
        self.best_chisq = np.NaN

    def create_model(self, params):
        """
        Creates a tweaked model based on the parameters passed,
        based on the reference spectrum.
        Stores the tweaked model in spectra.s_mod and serr_mod.
        """
        # Create a spline
        x = []
        y = []
        for i in range(params['num_knots'].value):
            p = 'knot_{0:d}'.format(i)
            x.append(params[p+'_x'].value)
            y.append(params[p+'_y'].value)
        s = UnivariateSpline(x, y, s=0)

        self.spectra['s_mod'] = s(self.spectra['w'])*self.spectra['s_ref']
        self.spectra['serr_mod'] = s(self.spectra['w'])*self.spectra['serr_ref']

        # Apply broadening kernel
        SPEED_OF_LIGHT = 2.99792e5
        dv = (self.spectra['w'].iloc[1]-self.spectra['w'].iloc[0])/self.spectra['w'].iloc[0]*SPEED_OF_LIGHT
        n = 151 # fixed number of points in the kernel
        vsini = params['vsini'].value
        varr, kernel = specmatchemp.kernels.rot(n, dv, vsini)
        self.spectra['s_mod'] = nd.convolve1d(self.spectra['s_mod'], kernel)
        self.spectra['serr_mod'] = nd.convolve1d(self.spectra['serr_mod'], kernel)

    def residual(self, params):
        """
        Objective function evaluating goodness of fit given the passed parameters

        Args:
            params
        Returns:
            Reduced chi-squared value between the target spectra and the 
            model spectrum generated by the parameters
        """
        self.create_model(params)

        # Calculate residuals
        diffsq = self.spectra['s_targ']-self.spectra['s_mod']
        variance = np.sqrt((self.spectra['serr_targ']**2+self.spectra['serr_mod']**2))

        return diffsq/variance

    def best_fit(self):
        """
        Calculates the best fit model by minimizing over the parameters:
        - spline fitting to the continuum
        - rotational broadening
        """
        # Create a spline with 5 knots
        params = lmfit.Parameters()
        num_knots = 5
        params.add('num_knots', value=num_knots, vary=False)
        interval = int(len(self.spectra)/(num_knots+1))

        # Add spline positions
        for i in range(num_knots):
            p = 'knot_{0:d}'.format(i)
            params.add(p+'_x', value=self.spectra['w'].iloc[interval*i], vary=False)
            params.add(p+'_y', value=self.spectra['s_targ'].iloc[interval*i])

        # Rotational broadening
        params.add('vsini', value=10.0, min=0.0)

        # Minimize chi-squared
        out = lmfit.minimize(self.residual, params)

        # Save best fit parameters
        self.best_params = out.params
        self.best_chisq = out.redchi
        self.create_model(self.best_params)



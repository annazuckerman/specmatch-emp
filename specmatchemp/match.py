"""
@filename match.py

Defines the Match class
"""

import numpy as np
import matplotlib.pyplot as plt
import lmfit
from scipy.interpolate import LSQUnivariateSpline
from scipy import signal
from scipy.ndimage.filters import convolve1d

import specmatchemp.kernels
from specmatchemp.spectrum import Spectrum
from specmatchemp import plots


class Match(object):
    def __init__(self, target, reference, mode='default', opt='nelder'):
        """
        The Match class used for matching two spectra

        Args:
            target (Spectrum): Target spectrum
            reference (Spectrum): Reference spectrum
            mode: default (unnormalized chi-square),
                  normalized (normalized chi-square)
            opt: lm (Levenberg-Marquadt optimization), nelder (Nelder-Mead)
        """

        if not np.allclose(target.w, reference.w):
            print("Target and reference are on different wavelength scales.")
            raise ValueError
        # common wavelength scale
        self.w = np.copy(target.w)

        # target, reference and modified spectra
        self.target = target.copy()
        self.reference = reference.copy()
        self.modified = reference.copy()

        # replace nans with continuum
        self.target.s[np.isnan(self.target.s)] = 1
        self.target.serr[np.isnan(self.target.serr)] = 1
        self.reference.s[np.isnan(self.reference.s)] = 1
        self.reference.serr[np.isnan(self.reference.serr)] = 1

        self.best_params = lmfit.Parameters()
        self.best_chisq = np.NaN
        self.mode = mode
        self.opt = opt

        # add spline knots
        num_knots = 5
        interval = int(len(self.w)/(num_knots+1))
        # Add spline positions
        self.knot_x = []
        for i in range(1, num_knots+1):
            self.knot_x.append(self.w[interval*i])
        self.knot_x = np.array(self.knot_x)

    def create_model(self, params):
        """
        Creates a tweaked model based on the parameters passed,
        based on the reference spectrum.
        Stores the tweaked model in spectra.s_mod and serr_mod.
        """
        self.modified.s = np.nan_to_num(self.reference.s)
        self.modified.serr = np.nan_to_num(self.reference.serr)

        # Apply broadening kernel
        vsini = params['vsini'].value
        self.modified = self.broaden(vsini, self.modified)

        # Use linear least squares to fit a spline
        spline = LSQUnivariateSpline(self.w, self.target.s / self.modified.s,
                                     self.knot_x)
        self.spl = spline(self.w)

        self.modified.s *= self.spl
        self.modified.serr *= self.spl

    def load_params(self, params):
        """
        Method to create a model based on pre-determined parameters,
        storing it as the best fit model.
        """
        self.best_chisq = self.objective(params)
        self.best_params = params

    def broaden(self, vsini, spec):
        """
        Applies a broadening kernel to the given spectrum (or error)

        Args:
            vsini (float): vsini to determine width of broadening
            spec (Spectrum): spectrum to broaden
        Returns:
            broadened (Spectrum): Broadened spectrum
        """
        SPEED_OF_LIGHT = 2.99792e5
        dv = (self.w[1]-self.w[0])/self.w[0]*SPEED_OF_LIGHT
        n = 151     # fixed number of points in the kernel
        varr, kernel = specmatchemp.kernels.rot(n, dv, vsini)
        # broadened = signal.fftconvolve(spec, kernel, mode='same')

        spec.s = convolve1d(spec.s, kernel)
        spec.serr = convolve1d(spec.serr, kernel)

        return spec

    def objective(self, params):
        """
        Objective function evaluating goodness of fit given the passed
        parameters.

        Args:
            params
        Returns:
            Reduced chi-squared value between the target spectra and the
            model spectrum generated by the parameters
        """
        self.create_model(params)

        # Calculate residuals (data - model)
        if self.mode == 'normalized':
            residuals = ((self.target.s - self.modified.s) /
                         np.sqrt(self.target.serr**2 + self.modified.serr**2))
        else:
            residuals = (self.target.s - self.modified.s)

        chi_square = np.sum(residuals**2)

        if self.opt == 'lm':
            return residuals
        elif self.opt == 'nelder':
            return chi_square

    def best_fit(self, params=None):
        """
        Calculates the best fit model by minimizing over the parameters:
        - spline fitting to the continuum
        - rotational broadening
        """
        if params is None:
            params = lmfit.Parameters()

        # Rotational broadening parameters
        params.add('vsini', value=1.0, min=0.0, max=10.0)

        # Spline parameters
        params = add_spline_positions(params, self.knot_x)

        # Perform fit
        if self.opt == 'lm':
            out = lmfit.minimize(self.objective, params)
            self.best_chisq = np.sum(self.objective(out.params)**2)
        elif self.opt == 'nelder':
            out = lmfit.minimize(self.objective, params, method='nelder')
            self.best_chisq = self.objective(out.params)

        self.best_params = out.params

        return self.best_chisq

    def best_residuals(self):
        """Returns the residuals between the target spectrum and best-fit
        spectrum.

        Returns:
            np.ndarray
        """
        if self.mode == 'normalized':
            return ((self.target.s - self.modified.s) /
                    np.sqrt(self.target.serr**2 + self.modified.serr**2))
        else:
            return (self.target.s - self.modified.s)  # data - model

    def get_spline_positions(self):
        """Wrapper function for getting spline positions

        Returns:
            knotx (np.ndarray)
        """
        return get_spline_positions(self.best_params)

    def plot(self, verbose=True):
        if verbose:
            labels = {'target': 'Target: {0}'.format(self.target.name),
                    'reference': 'Reference: {0}'.format(self.reference.name),
                    'modified': r'Reference (modified): $v\sin i = {0:.2f}$'
                                .format(self.best_params['vsini'].value),
                    'residuals': r'Residuals: $\chi^2 = {0:.3f}$'
                                .format(self.best_chisq)}
        else:
            labels = {'target': 'Target',
                      'reference': 'Reference',
                      'modified': 'Reference (Modified)',
                      'residuals': 'Residuals'}

        self.target.plot(text=labels['target'], plt_kw={'color': 'royalblue'})
        self.modified.plot(offset=1, plt_kw={'color': 'forestgreen'},
                           text=labels['modified'])
        self.reference.plot(offset=2, plt_kw={'color': 'firebrick'},
                            text=labels['reference'])

        plt.plot(self.target.w, self.modified.s-self.target.s,
                 '-', color='black')
        plots.annotate_spectrum(labels['residuals'], spec_offset=-1)


class MatchLincomb(Match):
    def __init__(self, target, refs, vsini, mode='default'):
        """
        Match subclass to find the best match from a linear combination of
        reference spectra.

        Args:
            target (Spectrum): Target spectrum
            refs (list of Spectrum): Array of reference spectra
            vsini (np.ndarray): array containing vsini broadening for each
                                reference spectrum
        """
        for i in range(len(refs)):
            if not np.allclose(target.w, refs[i].w):
                print("Target and reference {0:d} are on different".format(i) +
                      "wavelength scales.")
                raise ValueError

        self.w = np.copy(target.w)
        self.target = target.copy()
        self.num_refs = len(refs)
        self.refs = []
        for i in range(self.num_refs):
            self.refs.append(refs[i].copy())
        self.ref_chisq = None

        self.vsini = vsini

        # Broaden reference spectra
        self.broadened = []
        for i in range(self.num_refs):
            self.broadened.append(self.broaden(vsini[i], self.refs[i]))

        self.modified = Spectrum(self.w, name='Linear Combination {0:d}'
                                              .format(self.num_refs))

        self.best_params = lmfit.Parameters()
        self.best_chisq = np.NaN
        self.mode = mode
        self.opt = 'nelder'

        # add spline knots
        num_knots = 5
        interval = int(len(self.w)/(num_knots+1))
        # Add spline positions
        self.knot_x = []
        for i in range(1, num_knots+1):
            self.knot_x.append(self.w[interval*i])
        self.knot_x = np.array(self.knot_x)

    def create_model(self, params):
        """
        Creates a tweaked model based on the parameters passed,
        based on the reference spectrum.
        Stores the tweaked model in spectra.s_mod and serr_mod.
        """
        self.modified.s = np.zeros_like(self.w)
        self.modified.serr = np.zeros_like(self.w)

        # create the model from a linear combination of the reference spectra
        coeffs = get_lincomb_coeffs(params)
        for i in range(self.num_refs):
            self.modified.s += self.broadened[i].s * coeffs[i]
            self.modified.serr += self.broadened[i].serr * coeffs[i]

        # Use linear least squares to fit a spline
        spline = LSQUnivariateSpline(self.w, self.target.s / self.modified.s,
                                     self.knot_x)
        self.spl = spline(self.w)

        self.modified.s *= self.spl
        self.modified.serr *= self.spl

    def objective(self, params):
        """Objective function evaluating goodness of fit given the passed
        parameters.

        Args:
            params
        Returns:
            Reduced chi-squared value between the target spectra and the
            model spectrum generated by the parameters
        """
        chi_square = super().objective(params)

        # Add a Gaussian prior
        sum_coeff = np.sum(get_lincomb_coeffs(params))

        WIDTH = 1e-2
        chi_square += (sum_coeff - 1)**2 / (2 * WIDTH**2)

        return chi_square

    def best_fit(self):
        """
        Calculates the best fit model by minimizing over the parameters:
        - Coefficients of reference spectra
        - spline fitting to the continuum
        - rotational broadening
        """
        params = lmfit.Parameters()

        # Linear combination parameters
        params = add_lincomb_coeffs(params, self.num_refs)

        # Spline parameters
        params = add_spline_positions(params, self.knot_x)

        # vsini
        params = add_vsini(params, self.vsini)

        # Minimize chi-squared
        out = lmfit.minimize(self.objective, params, method='nelder')

        # Save best fit parameters
        self.best_params = out.params
        self.best_chisq = self.objective(self.best_params)

        return self.best_chisq

    def get_vsini(self):
        """Wrapper function to get vsini list from MatchLincomb object

        Returns:
            vsini (np.ndarray)
        """
        return get_vsini(self.best_params)

    def get_lincomb_coeffs(self):
        """Wrapper function to get lincomb coefficients from MatchLincomb object

        Returns:
            coeffs (np.ndarray)
        """
        return get_lincomb_coeffs(self.best_params)

    def plot(self, verbose=True):
        # create labels
        if verbose:
            labels = {'target': 'Target: {0}'.format(self.target.name),
                      'modified': r'Linear Combination',
                      'residuals': r'Residuals: $\chi^2 = {0:.3f}$'
                                   .format(self.best_chisq)}

            coeffs = self.get_lincomb_coeffs()

            for i in range(self.num_refs):
                if self.ref_chisq is None:
                    labels['ref_{0:d}'.format(i)] = (
                        'Reference: {0} '.format(self.refs[i].name) +
                        r'$v\sin i = {0:.2f}$ '.format(self.vsini[i]) +
                        r'$c_{0:d} = {1:.3f}$'.format(i, coeffs[i]))

                else:
                    labels['ref_{0:d}'.format(i)] = (
                        'Reference: {0} '.format(self.refs[i].name) +
                        r'$v\sin i = {0:.2f}$ '.format(self.vsini[i]) +
                        r'$\chi^2 = {0:.2f}$'.format(self.ref_chisq[i]) +
                        r'$c_{0:d} = {1:.3f}$'.format(i, coeffs[i]))
        else:
            labels = {'target': 'Target', 'modified': 'Reference (Modified)',
                      'residuals': 'Residuals'}

            for i in range(self.num_refs):
                labels['ref_{0:d}'.format(i)] = 'Reference {0:d}'.format(i)

        # Plot spectra
        self.target.plot(plt_kw={'color': 'royalblue'}, text=labels['target'])
        self.modified.plot(offset=0.5, plt_kw={'color': 'forestgreen'},
                           text=labels['modified'])

        for i in range(self.num_refs):
            self.refs[i].plot(offset=1.5+i*0.5, plt_kw={'color': 'firebrick'},
                              text=labels['ref_{0:d}'.format(i)])

        plt.plot(self.target.w, self.modified.s-self.target.s,
                 '-', color='black')
        plots.annotate_spectrum(labels['residuals'], spec_offset=-1)

        ylim = plt.ylim(ymin=-0.5)
        minor_ticks = np.arange(ylim[0], ylim[1], 0.5)
        plt.yticks(minor_ticks)
        plt.grid(True, which='both')


def add_spline_positions(params, knotx):
    """Adds spline positions to the parameter list.

    Args:
        params (lmfit.Parameters): parameters
        knotx (np.array): Array of knot positions
    Returns:
        params (lmfit.Parameters)
    """
    params.add('num_knots', value=len(knotx), vary=False)

    for i in range(len(knotx)):
        p = 'knotx_{0:d}'.format(i)
        params.add(p, value=knotx[i], vary=False)

    return params


def get_spline_positions(params):
    """Gets the spline positions from an lmfit parameters object.

    Args:
        params (lmfit.Parameters): parameters
    Returns:
        knotx (np.ndarray)
    """
    num_knots = params['num_knots'].value

    knotx = []
    for i in range(num_knots):
        p = 'knotx_{0:d}'.format(i)
        knotx.append(params[p].value)

    return np.array(knotx)


def add_vsini(params, vsini):
    """Adds vsini to an lmfit parameter list.

    Args:
        params (lmfit.Parameters): parameters
        vsini (np.ndarray): vsini values for each reference spectrum
    Returns:
        params (lmfit.Parameters)
    """
    if 'num_refs' not in params.valuesdict():
        params.add('num_refs', value=len(vsini), vary=False)

    for i in range(len(vsini)):
        p = 'vsini_{0:d}'.format(i)
        params.add(p, value=vsini[i], vary=False)

    return params


def get_vsini(params):
    """Gets vsini list from a parameters object.

    Args:
        params (lmfit.Parameters): parameters
    Returns:
        vsini (np.ndarray)
    """
    num_refs = params['num_refs'].value

    vsini = []
    for i in range(num_refs):
        p = 'vsini_{0:d}'.format(i)
        vsini.append(params[p].value)

    return np.array(vsini)


def add_lincomb_coeffs(params, num_refs):
    """Adds lincomb coefficients to an lmfit parameter list.

    Args:
        params (lmfit.Parameters): parameters
        num_refs (int): Number of reference spectra
    Returns:
        params (lmfit.Parameters)
    """
    if 'num_refs' not in params.valuesdict():
        params.add('num_refs', value=num_refs, vary=False)

    for i in range(num_refs):
        p = 'coeff_{0:d}'.format(i)
        params.add(p, value=1/num_refs, min=0.0, max=1.0)

    return params


def get_lincomb_coeffs(params):
    """Gets the lincomb coefficients form an lmfit parameter list.

    Args:
        params (lmfit.Paremters): parameters
    Returns:
        coeffs (np.ndarray)
    """
    num_refs = params['num_refs'].value

    coeffs = []
    for i in range(num_refs):
        p = 'coeff_{0:d}'.format(i)
        coeffs.append(params[p].value)

    return np.array(coeffs)

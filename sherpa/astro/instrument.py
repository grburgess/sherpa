#
#  Copyright (C) 2010, 2015-2018, 2019, 2020, 2021
#     Smithsonian Astrophysical Observator
#
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License along
#  with this program; if not, write to the Free Software Foundation, Inc.,
#  51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

"""
Models of common Astronomical models, particularly in X-rays.

The models in this module include support for instrument models that
describe how X-ray photons are converted to measurable properties,
such as Pulse-Height Amplitudes (PHA) or Pulse-Invariant channels.
These 'responses' are assumed to follow OGIP standards, such as
[1]_.

References
----------

.. [1] OGIP Calibration Memo CAL/GEN/92-002, "The Calibration Requirements
       for Spectral Analysis (Definition of RMF and ARF file formats)",
       Ian M. George1, Keith A. Arnaud, Bill Pence, Laddawan Ruamsuwan and
       Michael F. Corcoran,
       https://heasarc.gsfc.nasa.gov/docs/heasarc/caldb/docs/memos/cal_gen_92_002/cal_gen_92_002.html

"""

import os

import numpy

import sherpa
from sherpa.utils.err import InstrumentErr, DataErr, PSFErr
from sherpa.models.model import ArithmeticModel, CompositeModel, Model

from sherpa.instrument import PSFModel as _PSFModel
from sherpa.utils import NoNewAttributesAfterInit
from sherpa.data import Data1D
from sherpa.astro import hc
from sherpa.astro.data import DataARF, DataRMF, _notice_resp, DataIMG
from sherpa.utils import sao_fcmp, sum_intervals, sao_arange
from sherpa.astro.utils import compile_energy_grid

WCS = None
try:
    from sherpa.astro.io.wcs import WCS
except ImportError:
    WCS = None

_tol = numpy.finfo(numpy.float32).eps

string_types = (str, )


__all__ = ('RMFModel', 'ARFModel', 'RSPModel',
           'RMFModelPHA', 'RMFModelNoPHA',
           'ARFModelPHA', 'ARFModelNoPHA',
           'RSPModelPHA', 'RSPModelNoPHA',
           'MultiResponseSumModel', 'PileupRMFModel', 'RMF1D', 'ARF1D',
           'Response1D', 'MultipleResponse1D', 'PileupResponse1D',
           'PSFModel')


def apply_areascal(mdl, pha, instlabel):
    """Apply the AREASCAL conversion.

    This should be done after applying any RMF or ARF.

    Parameters
    ----------
    mdl : array
        The model values, after being passed through the response.
        The assumption is that the output is in channel space. No
        filtering is assumed to have been applied.
    pha : sherpa.astro.data.DataPHA object
        The PHA object containing the AREASCAL column, scalar, or
        None value.
    instlabel : str
        The name of the response (expected to be of the form
        'RMF: filename'). This is only used in case the size of out
        does not match the AREASCAL vector.

    Returns
    -------
    ans : array
        If AREASCAL is defined then the output is mdl * AREASCAL,
        otherwise it is just the input array (i.e. mdl).
    """

    ascal = pha.areascal
    if ascal is None:
        return mdl

    if numpy.iterable(ascal) and len(ascal) != len(mdl):
        raise DataErr('mismatch', instlabel,
                      'AREASCAL: {}'.format(pha.name))

    return mdl * ascal


class RMFModel(CompositeModel, ArithmeticModel):
    """Base class for expressing RMF convolution in model expressions.
    """

    def __init__(self, rmf, model):
        self.rmf = rmf
        self.model = model

        # Logic for ArithmeticModel.__init__
        self.pars = ()

        # FIXME: group pairs of coordinates with one attribute

        self.elo = None
        self.ehi = None  # Energy space
        self.lo = None
        self.hi = None   # Wavelength space
        self.xlo = None
        self.xhi = None  # Current Spectral coordinates

        # Used to rebin against finer or coarser energy grids
        self.rmfargs = ()

        CompositeModel.__init__(self, 'apply_rmf(%s)' % model.name, (model,))
        self.filter()

    def filter(self):
        # Energy grid (keV)
        self.elo, self.ehi = self.rmf.get_indep()

        # Wavelength grid (angstroms)
        self.lo, self.hi = hc / self.ehi, hc / self.elo

        # Assume energy as default spectral coordinates
        self.xlo, self.xhi = self.elo, self.ehi

        # Used to rebin against finer or coarser energy grids
        self.rmfargs = ()

    def startup(self, cache=False):
        self.model.startup(cache)
        CompositeModel.startup(self, cache)

    def teardown(self):
        self.model.teardown()
        CompositeModel.teardown(self)

    def calc(self, p, x, xhi=None, *args, **kwargs):
        raise NotImplementedError


class ARFModel(CompositeModel, ArithmeticModel):
    """Base class for expressing ARF convolution in model expressions.
    """

    def __init__(self, arf, model):
        self.arf = arf
        self.model = model

        self.elo = None
        self.ehi = None  # Energy space
        self.lo = None
        self.hi = None   # Wavelength space
        self.xlo = None
        self.xhi = None  # Current Spectral coordinates

        # Used to rebin against finer or coarser energy grids
        self.arfargs = ()

        # Logic for ArithmeticModel.__init__
        self.pars = ()

        CompositeModel.__init__(self, 'apply_arf(%s)' % model.name, (model,))
        self.filter()

    def filter(self):
        # Energy grid (keV)
        self.elo, self.ehi = self.arf.get_indep()

        # Wavelength grid (angstroms)
        self.lo, self.hi = hc / self.ehi, hc / self.elo

        # Assume energy as default spectral coordinates
        self.xlo, self.xhi = self.elo, self.ehi

        # Used to rebin against finer or coarser energy grids
        self.arfargs = ()

    def startup(self, cache=False):
        self.model.startup(cache)
        CompositeModel.startup(self, cache)

    def teardown(self):
        self.model.teardown()
        CompositeModel.teardown(self)

    def calc(self, p, x, xhi=None, *args, **kwargs):
        raise NotImplementedError


class RSPModel(CompositeModel, ArithmeticModel):
    """Base class for expressing RMF + ARF convolution in model expressions
    """

    def __init__(self, arf, rmf, model):
        self.arf = arf
        self.rmf = rmf
        self.model = model

        self.elo = None
        self.ehi = None  # Energy space
        self.lo = None
        self.hi = None    # Wavelength space
        self.xlo = None
        self.xhi = None  # Current Spectral coordinates

        # Used to rebin against finer or coarser energy grids
        self.rmfargs = ()
        self.arfargs = ()

        # Logic for ArithmeticModel.__init__
        self.pars = ()

        CompositeModel.__init__(self, 'apply_rmf(apply_arf(%s))' % model.name,
                                (model,))
        self.filter()

    def filter(self):
        # Energy grid (keV), ARF grid breaks tie
        self.elo, self.ehi = self.arf.get_indep()

        # Wavelength grid (angstroms)
        self.lo, self.hi = hc / self.ehi, hc / self.elo

        # Assume energy as default spectral coordinates
        self.xlo, self.xhi = self.elo, self.ehi

        # Used to rebin against finer or coarser energy grids
        self.rmfargs = ()
        self.arfargs = ()

    def startup(self, cache=False):
        self.model.startup(cache)
        CompositeModel.startup(self, cache)

    def teardown(self):
        self.model.teardown()
        CompositeModel.teardown(self)

    def calc(self, p, x, xhi=None, *args, **kwargs):
        raise NotImplementedError


class RMFModelPHA(RMFModel):
    """RMF convolution model with associated PHA data set.

    Notes
    -----
    Scaling by the AREASCAL setting (scalar or array) is included in
    this model.
    """

    def __init__(self, rmf, pha, model):
        self.pha = pha
        self._rmf = rmf  # store a reference to original
        RMFModel.__init__(self, rmf, model)

    def filter(self):

        RMFModel.filter(self)

        pha = self.pha
        # If PHA is a finer grid than RMF, evaluate model on PHA and
        # rebin down to the granularity that the RMF expects.
        if pha.bin_lo is not None and pha.bin_hi is not None:
            bin_lo, bin_hi = pha.bin_lo, pha.bin_hi

            # If PHA grid is in angstroms then convert to keV for
            # consistency
            if (bin_lo[0] > bin_lo[-1]) and (bin_hi[0] > bin_hi[-1]):
                bin_lo = hc / pha.bin_hi
                bin_hi = hc / pha.bin_lo

            # FIXME: What about filtered option?? bin_lo, bin_hi are
            # unfiltered??

            # Compare disparate grids in energy space
            self.rmfargs = ((self.elo, self.ehi), (bin_lo, bin_hi))

            # FIXME: Compute on finer energy grid?  Assumes that PHA has
            # finer grid than RMF
            self.elo, self.ehi = bin_lo, bin_hi

            # Wavelength grid (angstroms)
            self.lo, self.hi = hc / self.ehi, hc / self.elo

        # Assume energy as default spectral coordinates
        self.xlo, self.xhi = self.elo, self.ehi
        if self.pha.units == 'wavelength':
            self.xlo, self.xhi = self.lo, self.hi

    def startup(self, cache=False):
        rmf = self._rmf  # original

        # Create a view of original RMF
        self.rmf = DataRMF(rmf.name, rmf.detchans, rmf.energ_lo, rmf.energ_hi,
                           rmf.n_grp, rmf.f_chan, rmf.n_chan, rmf.matrix,
                           rmf.offset, rmf.e_min, rmf.e_max, rmf.header)

        # Filter the view for current fitting session
        _notice_resp(self.pha.get_noticed_channels(), None, self.rmf)

        self.filter()

        # Assume energy as default spectral coordinates
        self.xlo, self.xhi = self.elo, self.ehi
        if self.pha.units == 'wavelength':
            self.xlo, self.xhi = self.lo, self.hi

        RMFModel.startup(self, cache)

    def teardown(self):
        self.rmf = self._rmf

        self.filter()
        RMFModel.teardown(self)

    def calc(self, p, x, xhi=None, *args, **kwargs):
        # x is noticed/full channels here

        src = self.model.calc(p, self.xlo, self.xhi)
        out = self.rmf.apply_rmf(src, *self.rmfargs)

        return apply_areascal(out, self.pha,
                              "RMF: {}".format(self.rmf.name))


class RMFModelNoPHA(RMFModel):
    """RMF convolution model without an associated PHA data set.

    Notes
    -----
    Since there is no PHA data set, there is no correction for any
    AREASCAL setting associated with the data.
    """

    def __init__(self, rmf, model):
        RMFModel.__init__(self, rmf, model)

    def calc(self, p, x, xhi=None, *args, **kwargs):
        # x is noticed/full channels here

        # Always evaluates source model in keV!
        src = self.model.calc(p, self.xlo, self.xhi)
        return self.rmf.apply_rmf(src)


class ARFModelPHA(ARFModel):
    """ARF convolution model with associated PHA data set.

    Notes
    -----
    Scaling by the AREASCAL setting (scalar or array) is included in
    this model. It is not yet clear if this is handled correctly.
    """

    def __init__(self, arf, pha, model):
        self.pha = pha
        self._arf = arf  # store a reference to original
        ARFModel.__init__(self, arf, model)

    def filter(self):

        ARFModel.filter(self)

        pha = self.pha
        # If PHA is a finer grid than ARF, evaluate model on PHA and
        # rebin down to the granularity that the ARF expects.
        if pha.bin_lo is not None and pha.bin_hi is not None:
            bin_lo, bin_hi = pha.bin_lo, pha.bin_hi

            # If PHA grid is in angstroms then convert to keV for
            # consistency
            if (bin_lo[0] > bin_lo[-1]) and (bin_hi[0] > bin_hi[-1]):
                bin_lo = hc / pha.bin_hi
                bin_hi = hc / pha.bin_lo

            # FIXME: What about filtered option?? bin_lo, bin_hi are
            # unfiltered??

            # Compare disparate grids in energy space
            self.arfargs = ((self.elo, self.ehi), (bin_lo, bin_hi))

            # FIXME: Assumes ARF grid is finest

        # Assume energy as default spectral coordinates
        self.xlo, self.xhi = self.elo, self.ehi
        if self.pha.units == 'wavelength':
            self.xlo, self.xhi = self.lo, self.hi

    def startup(self, cache=False):
        arf = self._arf  # original
        pha = self.pha

        # Create a view of original ARF
        self.arf = DataARF(arf.name, arf.energ_lo, arf.energ_hi, arf.specresp,
                           arf.bin_lo, arf.bin_hi, arf.exposure, arf.header)

        # Filter the view for current fitting session
        if numpy.iterable(pha.mask):
            mask = pha.get_mask()
            if len(mask) == len(self.arf.specresp):
                self.arf.notice(mask)

        self.filter()

        # Assume energy as default spectral coordinates
        self.xlo, self.xhi = self.elo, self.ehi
        if pha.units == 'wavelength':
            self.xlo, self.xhi = self.lo, self.hi

        ARFModel.startup(self, cache)

    def teardown(self):
        self.arf = self._arf  # restore original

        self.filter()
        ARFModel.teardown(self)

    def calc(self, p, x, xhi=None, *args, **kwargs):
        # x could be channels or x, xhi could be energy|wave

        src = self.model.calc(p, self.xlo, self.xhi)
        src = self.arf.apply_arf(src, *self.arfargs)

        return apply_areascal(src, self.pha,
                              "ARF: {}".format(self.arf.name))


class ARFModelNoPHA(ARFModel):
    """ARF convolution model without associated PHA data set.

    Notes
    -----
    Since there is no PHA data set, there is no correction for any
    AREASCAL setting associated with the data.
    """

    def __init__(self, arf, model):
        ARFModel.__init__(self, arf, model)

    def calc(self, p, x, xhi=None, *args, **kwargs):
        # x could be channels or x, xhi could be energy|wave

        # if (xhi is not None and
        #    x[0] > x[-1] and xhi[0] > xhi[-1]):
        #    xlo, xhi = self.lo, self.hi
        # else:

        # Always evaluates source model in keV!
        src = self.model.calc(p, self.xlo, self.xhi)
        return self.arf.apply_arf(src)


class RSPModelPHA(RSPModel):
    """RMF + ARF convolution model with associated PHA.

    Notes
    -----
    Scaling by the AREASCAL setting (scalar or array) is included in
    this model.
    """

    def __init__(self, arf, rmf, pha, model):
        self.pha = pha
        self._arf = arf
        self._rmf = rmf
        RSPModel.__init__(self, arf, rmf, model)

    def filter(self):

        RSPModel.filter(self)

        pha = self.pha
        # If PHA is a finer grid than RMF, evaluate model on PHA and
        # rebin down to the granularity that the RMF expects.
        if pha.bin_lo is not None and pha.bin_hi is not None:
            bin_lo, bin_hi = pha.bin_lo, pha.bin_hi

            # If PHA grid is in angstroms then convert to keV for
            # consistency
            if (bin_lo[0] > bin_lo[-1]) and (bin_hi[0] > bin_hi[-1]):
                bin_lo = hc / pha.bin_hi
                bin_hi = hc / pha.bin_lo

            # FIXME: What about filtered option?? bin_lo, bin_hi are
            # unfiltered??

            # Compare disparate grids in energy space
            self.arfargs = ((self.elo, self.ehi), (bin_lo, bin_hi))

            # FIXME: Assumes ARF grid is finest

        elo, ehi = self.rmf.get_indep()
        # self.elo, self.ehi are from ARF
        if len(elo) != len(self.elo) and len(ehi) != len(self.ehi):

            self.rmfargs = ((elo, ehi), (self.elo, self.ehi))

        # Assume energy as default spectral coordinates
        self.xlo, self.xhi = self.elo, self.ehi
        if self.pha.units == 'wavelength':
            self.xlo, self.xhi = self.lo, self.hi

    def startup(self, cache=False):
        arf = self._arf
        rmf = self._rmf

        # Create a view of original RMF
        self.rmf = DataRMF(rmf.name, rmf.detchans, rmf.energ_lo, rmf.energ_hi,
                           rmf.n_grp, rmf.f_chan, rmf.n_chan, rmf.matrix,
                           rmf.offset, rmf.e_min, rmf.e_max, rmf.header)

        # Create a view of original ARF
        self.arf = DataARF(arf.name, arf.energ_lo, arf.energ_hi, arf.specresp,
                           arf.bin_lo, arf.bin_hi, arf.exposure, arf.header)

        # Filter the view for current fitting session
        _notice_resp(self.pha.get_noticed_channels(), self.arf, self.rmf)

        self.filter()

        # Assume energy as default spectral coordinates
        self.xlo, self.xhi = self.elo, self.ehi
        if self.pha.units == 'wavelength':
            self.xlo, self.xhi = self.lo, self.hi

        RSPModel.startup(self, cache)

    def teardown(self):
        self.arf = self._arf  # restore originals
        self.rmf = self._rmf

        self.filter()
        RSPModel.teardown(self)

    def calc(self, p, x, xhi=None, *args, **kwargs):
        # x could be channels or x, xhi could be energy|wave

        src = self.model.calc(p, self.xlo, self.xhi)
        src = self.arf.apply_arf(src, *self.arfargs)
        src = self.rmf.apply_rmf(src, *self.rmfargs)

        # Assume any issues with the binning (between AREASCAL
        # and src) is related to the RMF rather than the ARF.
        return apply_areascal(src, self.pha,
                              "RMF: {}".format(self.rmf.name))


class RSPModelNoPHA(RSPModel):
    """RMF + ARF convolution model without associated PHA data set.

    Notes
    -----
    Since there is no PHA data set, there is no correction for any
    AREASCAL setting associated with the data.
    """

    def __init__(self, arf, rmf, model):
        RSPModel.__init__(self, arf, rmf, model)

    def calc(self, p, x, xhi=None, *args, **kwargs):
        # x could be channels or x, xhi could be energy|wave

        # Always evaluates source model in keV!
        src = self.model.calc(p, self.xlo, self.xhi)
        src = self.arf.apply_arf(src, *self.arfargs)
        return self.rmf.apply_rmf(src, *self.rmfargs)


class ARF1D(NoNewAttributesAfterInit):

    def __init__(self, arf, pha=None, rmf=None):
        self._arf = arf
        self._pha = pha
        NoNewAttributesAfterInit.__init__(self)

    def __getattr__(self, name):
        arf = None
        try:
            arf = ARF1D.__getattribute__(self, '_arf')
        except:
            pass

        if name in ('_arf', '_pha'):
            return self.__dict__[name]

        if arf is not None:
            return DataARF.__getattribute__(arf, name)

        return ARF1D.__getattribute__(self, name)

    def __setattr__(self, name, val):
        arf = None
        try:
            arf = ARF1D.__getattribute__(self, '_arf')
        except:
            pass

        if arf is not None and hasattr(arf, name):
            DataARF.__setattr__(arf, name, val)
        else:
            NoNewAttributesAfterInit.__setattr__(self, name, val)

    def __dir__(self):
        return dir(self._arf)

    def __str__(self):
        return str(self._arf)

    def __repr__(self):
        return repr(self._arf)

    def __call__(self, model, session=None):
        arf = self._arf
        pha = self._pha

        if isinstance(model, string_types):
            if session is None:
                model = sherpa.astro.ui._session._eval_model_expression(model)
            else:
                model = session._eval_model_expression(model)

        # Automatically add exposure time to source model
        if pha is not None and pha.exposure is not None:
            model = pha.exposure * model
        elif arf.exposure is not None:
            model = arf.exposure * model
        # FIXME: display a warning if exposure is None?

        if pha is not None:
            return ARFModelPHA(arf, pha, model)

        return ARFModelNoPHA(arf, model)


class RMF1D(NoNewAttributesAfterInit):

    def __init__(self, rmf, pha=None, arf=None):
        self._rmf = rmf
        self._arf = arf
        self._pha = pha
        NoNewAttributesAfterInit.__init__(self)

    def __getattr__(self, name):
        rmf = None
        try:
            rmf = RMF1D.__getattribute__(self, '_rmf')
        except:
            pass

        if name in ('_rmf', '_pha'):
            return self.__dict__[name]

        if rmf is not None:
            return DataRMF.__getattribute__(rmf, name)

        return RMF1D.__getattribute__(self, name)

    def __setattr__(self, name, val):
        rmf = None
        try:
            rmf = RMF1D.__getattribute__(self, '_rmf')
        except:
            pass

        if rmf is not None and hasattr(rmf, name):
            DataRMF.__setattr__(rmf, name, val)
        else:
            NoNewAttributesAfterInit.__setattr__(self, name, val)

    def __dir__(self):
        return dir(self._rmf)

    def __str__(self):
        return str(self._rmf)

    def __repr__(self):
        return repr(self._rmf)

    def __call__(self, model, session=None):
        arf = self._arf
        rmf = self._rmf
        pha = self._pha

        if isinstance(model, string_types):
            if session is None:
                model = sherpa.astro.ui._session._eval_model_expression(model)
            else:
                model = session._eval_model_expression(model)

        # Automatically add exposure time to source model for RMF-only analysis
        if type(model) not in (ARFModel, ARFModelPHA, ARFModelNoPHA):

            if pha is not None and pha.exposure is not None:
                model = pha.exposure * model
            elif arf is not None and arf.exposure is not None:
                model = arf.exposure * model
        elif pha is not None and arf is not None:
            # If model is an ARF?
            # Replace RMF(ARF(SRC)) with RSP(SRC) for efficiency
            return RSPModelPHA(arf, rmf, pha, model.model)

        if pha is not None:
            return RMFModelPHA(rmf, pha, model)

        return RMFModelNoPHA(rmf, model)


class Response1D(NoNewAttributesAfterInit):
    """A factory class for generating the instrument response.

    This should not be used when a pileup model is required.

    Parameters
    ----------
    pha : sherpa.astro.data.DataPHA instance
        The data object which defines the channel grid and instrument
        response. There must be either an ARF or RMF associated
        with the dataset.

    Raises
    ------
    sherpa.utils.err.DataErr
        The argument does not contain any response information (it is
        missing an ARF and a RMF).

    See Also
    --------
    MultipleResponse1D, PileupResponse1D

    Notes
    -----
    When the object is called it can be sent a ``session`` parameter,
    which defines the session to use when converting a string model to
    a ArithmeticModel instance. It is not used for any other function.
    The default value for this parameter is `None`, in which case the
    code uses the sherpa.astro.ui._session object.

    The response will include the exposure time if is is defined in
    either the PHA or ARF datasets (PHA taking precedence). The final
    response will be one of RSPModelPHA, ARFModelPHA, or RMFModelPHA.

    Examples
    --------

    Add the response to a model (``src_model``) and then evaluate it.
    The response will ignore the input argument, and evaluate it for
    all channels (hence the use of a dummy argument [1]):

    >>> rsp = Response1D(pha)
    >>> full_model = rsp(src_model)
    >>> ycnts = full_model([1])

    """

    def __init__(self, pha):
        self.pha = pha
        arf, rmf = pha.get_response()
        if arf is None and rmf is None:
            raise DataErr('norsp', pha.name)

        NoNewAttributesAfterInit.__init__(self)

    def __call__(self, model, session=None):
        pha = self.pha
        arf, rmf = pha.get_response()

        if isinstance(model, string_types):
            if session is None:
                model = sherpa.astro.ui._session._eval_model_expression(model)
            else:
                model = session._eval_model_expression(model)

        # Automatically add exposure time to source model
        if pha.exposure is not None:
            model = pha.exposure * model
        elif arf is not None and arf.exposure is not None:
            model = arf.exposure * model

        if arf is not None and rmf is not None:
            return RSPModelPHA(arf, rmf, pha, model)

        if arf is not None:
            return ARFModelPHA(arf, pha, model)

        if rmf is not None:
            return RMFModelPHA(rmf, pha, model)

        raise DataErr('norsp', pha.name)


class ResponseNestedModel(Model):

    def __init__(self, arf=None, rmf=None):
        self.arf = arf
        self.rmf = rmf

        name = ''
        if arf is not None and rmf is not None:
            name = 'apply_rmf(apply_arf('
        elif arf is not None:
            name = 'apply_arf('
        elif rmf is not None:
            name = 'apply_rmf('
        Model.__init__(self, name)

    def calc(self, p, *args, **kwargs):
        arf = self.arf
        rmf = self.rmf

        if arf is not None and rmf is not None:
            return rmf.apply_rmf(arf.apply_arf(*args, **kwargs))
        elif self.arf is not None:
            return arf.apply_arf(*args, **kwargs)

        return rmf.apply_rmf(*args, **kwargs)


class MultiResponseSumModel(CompositeModel, ArithmeticModel):

    def __init__(self, source, pha):
        self.channel = pha.channel
        self.mask = numpy.ones(len(pha.channel), dtype=bool)
        self.pha = pha
        self.source = source
        self.elo = None
        self.ehi = None
        self.lo = None
        self.hi = None
        self.table = None
        self.orders = None

        models = []
        grid = []

        for id in pha.response_ids:
            arf, rmf = pha.get_response(id)

            if arf is None and rmf is None:
                raise DataErr('norsp', pha.name)

            m = ResponseNestedModel(arf, rmf)
            indep = None

            if arf is not None:
                indep = arf.get_indep()

            if rmf is not None:
                indep = rmf.get_indep()

            models.append(m)
            grid.append(indep)

        self.models = models
        self.grid = grid

        name = '%s(%s)' % (type(self).__name__,
                           ','.join(['%s(%s)' % (m.name, source.name)
                                     for m in models]))
        CompositeModel.__init__(self, name, (source,))

    def _get_noticed_energy_list(self):
        grid = []
        for id in self.pha.response_ids:
            arf, rmf = self.pha.get_response(id)
            indep = None
            if arf is not None:
                indep = arf.get_indep()
            elif rmf is not None:
                indep = rmf.get_indep()
            grid.append(indep)

        self.elo, self.ehi, self.table = compile_energy_grid(grid)
        self.lo, self.hi = hc / self.ehi, hc / self.elo

    def startup(self, cache=False):
        pha = self.pha
        if numpy.iterable(pha.mask):
            pha.notice_response(True)
        self.channel = pha.get_noticed_channels()
        self.mask = pha.get_mask()
        self._get_noticed_energy_list()
        CompositeModel.startup(self, cache)

    def teardown(self):
        pha = self.pha
        if numpy.iterable(pha.mask):
            pha.notice_response(False)
        self.channel = pha.channel
        self.mask = numpy.ones(len(pha.channel), dtype=bool)
        self.elo = None
        self.ehi = None
        self.table = None
        self.lo = None
        self.hi = None
        CompositeModel.teardown(self)

    def _check_for_user_grid(self, x, xhi=None):
        return (len(self.channel) != len(x) or
                not (sao_fcmp(self.channel, x, _tol) == 0).all())

    def _startup_user_grid(self, x, xhi=None):
        # fit() never comes in here b/c it calls startup()
        pha = self.pha
        self.mask = numpy.zeros(len(pha.channel), dtype=bool)
        self.mask[numpy.searchsorted(pha.channel, x)] = True
        pha.notice_response(True, x)
        self._get_noticed_energy_list()

    def _teardown_user_grid(self):
        # fit() never comes in here b/c it calls startup()
        pha = self.pha
        self.mask = numpy.ones(len(pha.channel), dtype=bool)
        pha.notice_response(False)
        self.elo = None
        self.ehi = None
        self.table = None
        self.lo = None
        self.hi = None

    def calc(self, p, x, xhi=None, *args, **kwargs):
        pha = self.pha

        # TODO: this should probably include AREASCAL

        user_grid = False
        try:

            if self._check_for_user_grid(x, xhi):
                user_grid = True
                self._startup_user_grid(x, xhi)

            # Slow
            if self.table is None:
                # again, fit() never comes in here b/c it calls startup()
                src = self.source
                vals = []
                for model, args in zip(self.models, self.grid):
                    elo, ehi = lo, hi = args
                    if pha.units == 'wavelength':
                        lo = hc / ehi
                        hi = hc / elo
                    vals.append(model(src(lo, hi)))
                self.orders = vals
            # Fast
            else:
                xlo, xhi = self.elo, self.ehi
                if pha.units == 'wavelength':
                    xlo, xhi = self.lo, self.hi

                src = self.source(xlo, xhi)  # hi-res grid of all ARF grids

                # Fold summed intervals through the associated response.
                self.orders = \
                    [model(sum_intervals(src, interval[0], interval[1]))
                     for model, interval in zip(self.models, self.table)]

            vals = sum(self.orders)
            if self.mask is not None:
                vals = vals[self.mask]

        finally:
            if user_grid:
                self._teardown_user_grid()

        return vals


class MultipleResponse1D(Response1D):
    """A factory class for generating the instrument response.

    This should not be used when a pileup model is required.

    Parameters
    ----------
    pha : sherpa.astro.data.DataPHA instance
        Support PHA files with multiple responses (e.g. orders) to
        describe the data.

    Raises
    ------
    sherpa.utils.err.DataErr
        The argument does not contain any response information (it is
        missing an ARF and a RMF).

    See Also
    --------
    Response1D

    """

    def __call__(self, model, session=None):
        pha = self.pha

        if isinstance(model, string_types):
            if session is None:
                model = sherpa.astro.ui._session._eval_model_expression(model)
            else:
                model = session._eval_model_expression(model)

        pha.notice_response(False)

        model = MultiResponseSumModel(model, pha)

        # TODO: should this include AREASCAL?
        if pha.exposure:
            model = pha.exposure * model

        return model


class PileupRMFModel(CompositeModel, ArithmeticModel):

    def __init__(self, rmf, model, pha=None):
        self.pha = pha
        self.channel = sao_arange(1, rmf.detchans)  # sao_arange is inclusive
        self.mask = numpy.ones(rmf.detchans, dtype=bool)
        self.rmf = rmf

        self.elo, self.ehi = rmf.get_indep()
        self.lo, self.hi = hc / self.ehi, hc / self.elo
        self.model = model
        self.otherargs = None
        self.otherkwargs = None
        self.pars = ()
        CompositeModel.__init__(self,
                                ('%s(%s)' % ('apply_rmf', self.model.name)),
                                (self.model,))

    def startup(self, cache=False):
        pha = self.pha
        pha.notice_response(False)
        self.channel = pha.get_noticed_channels()
        self.mask = pha.get_mask()
        self.model.startup(cache)
        CompositeModel.startup(self, cache)

    def teardown(self):

        # Note:
        #
        # The pha variable was declared but not used, so has been commented
        # out. It has been kept as a comment for future review, since it
        # is unclear whether anything should be done to the PHA object
        # during teardown
        #
        # pha = self.pha

        rmf = self.rmf
        self.channel = sao_arange(1, rmf.detchans)
        self.mask = numpy.ones(rmf.detchans, dtype=bool)
        self.model.teardown()
        CompositeModel.teardown(self)

    def _check_for_user_grid(self, x):
        return (len(self.channel) != len(x) or
                not (sao_fcmp(self.channel, x, _tol) == 0).all())

    def _startup_user_grid(self, x):
        # fit() never comes in here b/c it calls startup()
        self.mask = numpy.zeros(self.rmf.detchans, dtype=bool)
        self.mask[numpy.searchsorted(self.pha.channel, x)] = True

    def _calc(self, p, xlo, xhi):
        # Evaluate source model on RMF energy/wave grid OR
        # model.calc --> pileup_model
        src = self.model.calc(p, xlo, xhi)

        # rmf_fold
        return self.rmf.apply_rmf(src)

    def calc(self, p, x, xhi=None, **kwargs):
        pha = self.pha
        # x is noticed/full channels here

        user_grid = False
        try:
            if self._check_for_user_grid(x):
                user_grid = True
                self._startup_user_grid(x)

            xlo, xhi = self.elo, self.ehi
            if pha is not None and pha.units == 'wavelength':
                xlo, xhi = self.lo, self.hi

            vals = self._calc(p, xlo, xhi)
            if self.mask is not None:
                vals = vals[self.mask]

        finally:
            if user_grid:
                self.mask = numpy.ones(self.rmf.detchans, dtype=bool)

        return vals


class PileupResponse1D(NoNewAttributesAfterInit):
    """A factory class for generating a response including pileup.

    Parameters
    ----------
    pha : sherpa.astro.data.DataPHA instance
        The data object which defines the channel grid and instrument
        response. There must be both an ARF or RMF associated
        with the dataset when it is called.
    pileup_model : sherpa.astro.models.JDPileup instance
        The pileup model.

    Raises
    ------
    sherpa.utils.err.DataErr
        The argument does not contain any response information (it is
        missing an ARF or RMF).

    See Also
    --------
    Response1D

    """

    def __init__(self, pha, pileup_model):
        self.pha = pha
        self.pileup_model = pileup_model
        NoNewAttributesAfterInit.__init__(self)

    def __call__(self, model, session=None):
        pha = self.pha
        # clear out any previous response filter
        pha.notice_response(False)

        if isinstance(model, string_types):
            if session is None:
                model = sherpa.astro.ui._session._eval_model_expression(model)
            else:
                model = session._eval_model_expression(model)

        arf, rmf = pha.get_response()
        err_msg = None

        if arf is None and rmf is None:
            raise DataErr('norsp', pha.name)

        if arf is None:
            err_msg = 'does not have an associated ARF'
        elif pha.exposure is None:
            err_msg = 'does not specify an exposure time'

        if err_msg:
            raise InstrumentErr('baddata', pha.name, err_msg)

        # Currently, the response is NOT noticed using pileup

        # ARF convolution done inside ISIS pileup module
        # on finite grid scale
        model = model.apply(self.pileup_model, pha.exposure, arf.energ_lo,
                            arf.energ_hi, arf.specresp, model)

        if rmf is not None:
            model = PileupRMFModel(rmf, model, pha)
        return model


class PSFModel(_PSFModel):

    def fold(self, data):
        _PSFModel.fold(self, data)

        # Set WCS coordinates of kernel data set to match source data set.
        if hasattr(self.kernel, "set_coord"):
            self.kernel.set_coord(data.coord)

    def get_kernel(self, data, subkernel=True):

        indep, dep, kshape, lo, hi = self._get_kernel_data(data, subkernel)

        # Use kernel data set WCS if available
        eqpos = getattr(self.kernel, 'eqpos', None)
        sky = getattr(self.kernel, 'sky', None)

        # If kernel is a model, use WCS from data if available
        if callable(self.kernel):
            eqpos = getattr(data, 'eqpos', None)
            sky = getattr(data, 'sky', None)

        dataset = None
        ndim = len(kshape)
        if ndim == 1:
            dataset = Data1D('kernel', indep[0], dep)

        elif ndim == 2:

            # Edit WCS to reflect the subkernel extraction in
            # physical coordinates.
            if (subkernel and sky is not None and
                    lo is not None and hi is not None):

                if (WCS is not None):
                    sky = WCS(sky.name, sky.type, sky.crval,
                              sky.crpix - lo, sky.cdelt, sky.crota,
                              sky.epoch, sky.equinox)

                # FIXME: Support for WCS only (non-Chandra) coordinate
                # transformations?

            dataset = DataIMG('kernel', indep[0], indep[1], dep,
                              kshape[::-1], sky=sky, eqpos=eqpos)
        else:
            raise PSFErr('ndim')

        return dataset


def create_arf(elo, ehi, specresp=None, exposure=None, ethresh=None,
               name='user-arf', header=None):
    """Create an ARF.

    .. versionadded:: 4.10.1

    Parameters
    ----------
    elo, ehi : numpy.ndarray
        The energy bins (low and high, in keV) for the ARF. It is
        assumed that ehi_i > elo_i, elo_j > 0, the energy bins are
        either ascending - so elo_i+1 > elo_i - or descending
        (elo_i+1 < elo_i), and that there are no overlaps.
    specresp : None or array, optional
        The spectral response (in cm^2) for the ARF. It is assumed
        to be >= 0. If not given a flat response of 1.0 is used.
    exposure : number or None, optional
        If not None, the exposure of the ARF in seconds.
    ethresh : number or None, optional
        Passed through to the DataARF call. It controls whether
        zero-energy bins are replaced.
    name : str, optional
        The name of the ARF data set
    header : dict
        Header for the created ARF

    Returns
    -------
    arf : sherpa.astro.data.DataARF instance

    See Also
    --------
    create_delta_rmf, create_non_delta_rmf
    """

    if specresp is None:
        specresp = numpy.ones(elo.size, dtype=numpy.float32)

    return DataARF(name, energ_lo=elo, energ_hi=ehi, specresp=specresp,
                   exposure=exposure, ethresh=ethresh, header=header)


# Notes for create*rmf:
#  - I do not think I have the startchan=0 case correct. Does the
#    f_chan array have to change?
#

def create_delta_rmf(rmflo, rmfhi, offset=1,
                     e_min=None, e_max=None, ethresh=None,
                     name='delta-rmf', header=None):
    """Create an ideal RMF.

    The RMF has a unique mapping from channel to energy, in
    that each channel maps exactly to one energy bin, the
    mapping is monotonic, and there are no gaps.

    .. versionadded:: 4.10.1

    Parameters
    ----------
    rmflo, rmfhi : array
        The energy bins (low and high, in keV) for the RMF.
        It is assumed that emfhi_i > rmflo_i, rmflo_j > 0, that the energy
        bins are either ascending, so rmflo_i+1 > rmflo_i or descending
        (rmflo_i+1 < rmflo_i), and that there are no overlaps.
        These correspond to the Elow and Ehigh columns (represented
        by the ENERG_LO and ENERG_HI columns of the MATRIX block) of
        the OGIP standard.
    offset : int, optional
        The starting channel number: expected to be 0 or 1 but this is
        not enforced.
    e_min, e_max : None or array, optional
        The E_MIN and E_MAX columns of the EBOUNDS block of the
        RMF.
    ethresh : number or None, optional
        Passed through to the DataRMF call. It controls whether
        zero-energy bins are replaced.
    name : str, optional
        The name of the RMF data set
    header : dict
        Header for the created RMF

    Returns
    -------
    rmf : DataRMF instance

    See Also
    --------
    create_arf, create_non_delta_rmf
    """

    # Set up the delta-function response.
    # TODO: should f_chan start at startchan?
    #
    nchans = rmflo.size
    matrix = numpy.ones(nchans, dtype=numpy.float32)
    dummy = numpy.ones(nchans, dtype=numpy.int16)
    f_chan = numpy.arange(1, nchans + 1, dtype=numpy.int16)

    return sherpa.astro.data.DataRMF(name, detchans=nchans,
                                     energ_lo=rmflo, energ_hi=rmfhi,
                                     n_grp=dummy, n_chan=dummy,
                                     f_chan=f_chan, matrix=matrix,
                                     offset=offset,
                                     e_min=e_min, e_max=e_max,
                                     ethresh=ethresh, header=header)


def create_non_delta_rmf(rmflo, rmfhi, fname, offset=1,
                         e_min=None, e_max=None, ethresh=None,
                         name='delta-rmf', header=None):
    """
    Create a RMF using a matrix from a file.

    The RMF matrix (the mapping from channel to energy bin) is
    read in from a file.

    .. versionadded:: 4.10.1

    Parameters
    ----------
    rmflo, rmfhi : array
        The energy bins (low and high, in keV) for the RMF.
        It is assumed that emfhi_i > rmflo_i, rmflo_j > 0, that the energy
        bins are either ascending, so rmflo_i+1 > rmflo_i or descending
        (rmflo_i+1 < rmflo_i), and that there are no overlaps.
        These correspond to the Elow and Ehigh columns (represented
        by the ENERG_LO and ENERG_HI columns of the MATRIX block) of
        the OGIP standard.
    fname : str
        The name of the two-dimensional image file which stores the
        response information (the format of this file matches that
        created by the CIAO tool rmfimg [1]_).
    offset : int, optional
        The starting channel number: expected to be 0 or 1 but this is
        not enforced.
    e_min, e_max : None or array, optional
        The E_MIN and E_MAX columns of the EBOUNDS block of the
        RMF.
    ethresh : number or None, optional
        Passed through to the DataRMF call. It controls whether
        zero-energy bins are replaced.
    name : str
        The name of the RMF data set
    header : dict
        Header for the created RMF

    Returns
    -------
    rmf : DataRMF instance

    See Also
    --------
    create_arf, create_delta_rmf

    References
    ----------

    .. [1] http://cxc.harvard.edu/ciao/ahelp/rmfimg.html

    """

    if fname is not None and not os.path.isfile(fname):
        raise ValueError("{} is not a file".format(fname))

    # Set up the delta-function response.
    # TODO: should f_chan start at startchan?
    #
    nchans = rmflo.size

    n_grp, f_chan, n_chan, matrix = calc_grp_chan_matrix(fname)

    return sherpa.astro.data.DataRMF(name, detchans=nchans,
                                     energ_lo=rmflo, energ_hi=rmfhi,
                                     n_grp=n_grp, n_chan=n_chan,
                                     f_chan=f_chan, matrix=matrix,
                                     offset=offset,
                                     e_min=e_min, e_max=e_max,
                                     ethresh=ethresh,
                                     header=header)


def calc_grp_chan_matrix(fname):
    try:
        data, filename = \
            sherpa.astro.io.backend.get_image_data(fname)
        matrix = data['y']
        n_grp = []
        n_chan = []
        f_chan = []
        for row in matrix > 0:
            flag = numpy.hstack([[0], row, [0]])
            diffs = numpy.diff(flag, n=1)
            starts, = numpy.where(diffs > 0)
            ends, = numpy.where(diffs < 0)
            n_chan.extend(ends - starts)
            f_chan.extend(starts + 1)
            n_grp.append(len(starts))
        n_grp = numpy.asarray(n_grp, dtype=numpy.int16)
        f_chan = numpy.asarray(f_chan, dtype=numpy.int16)
        n_chan = numpy.asarray(n_chan, dtype=numpy.int16)
        matrix = matrix.flatten()
        matrix = matrix[matrix > 0]
        return n_grp, f_chan, n_chan, matrix
    except sherpa.utils.err.IOErr as ioerr:
        print(ioerr)
        raise ioerr


def has_pha_response(model):
    """Does the model contain a PHA response?

    Parameters
    ----------
    model : Model instance
        The model expression to check.

    Returns
    -------
    flag : bool
        True if there is a PHA response included anywhere in the
        expression.

    Examples
    --------

    >>> rsp = Response1D(pha)
    >>> m1 = Gauss1D()
    >>> m2 = PowLaw1D()
    >>> has_pha_response(m1)
    False
    >>> has_pha_response(rsp(m1))
    True
    >>> has_pha_response(m1 + m2)
    False
    >>> has_pha_response(rsp(m1 + m2))
    True
    >>> has_pha_response(m1 + rsp(m2))
    True

    """

    # The following check should probably include ResponseNestedModel
    # but it's not obvious if this is currently used.
    #
    def wanted(c):
        return isinstance(c, (RSPModel, ARFModel, RMFModel))

    if wanted(model):
        return True

    # This check relies on a composite class like the RSPModel is
    # included in the __iter__ method (see CompositeModel._get_parts)
    # otherwise the following would have had to be a recursive call
    # to has_pha_instance.
    #
    for cpt in model:
        if wanted(cpt):
            return True

    return False

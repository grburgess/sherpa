#
#  Copyright (C) 2007, 2015, 2016, 2018, 2020
#       Smithsonian Astrophysical Observatory
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

import logging
import numpy
import pytest

from sherpa.utils.testing import requires_data, \
    requires_xspec, requires_fits
from sherpa.data import Data1D
from sherpa.astro.data import DataPHA

from sherpa.models import PowLaw1D, SimulFitModel
from sherpa.data import DataSimulFit
from sherpa.fit import Fit
from sherpa.stats import Cash, CStat, WStat, LeastSq, UserStat, \
    Chi2Gehrels, Chi2ConstVar, Chi2ModVar, Chi2XspecVar, Chi2DataVar
from sherpa.optmethods import LevMar, NelderMead
from sherpa.utils.err import StatErr
from sherpa.astro import ui

logger = logging.getLogger("sherpa")


class MySimulStat(UserStat):

    def __init__(self, name='mysimulstat'):
        UserStat.__init__(self, name)

    @staticmethod
    def mycal_staterror(data):
        return numpy.ones_like(data)

    """
    @staticmethod
    def my_simulstat(data, model, staterror, *args, **kwargs):
        data_size = kwargs['extra_args']['data_size']
        data1 = data[:data_size[0]]
        data2 = data[data_size[0]:]
        model1 = model[:data_size[0]]
        model2 = model[data_size[0]:]
        staterror1 = staterror[:data_size[0]]
        staterror2 = staterror[data_size[0]:]
        mystat1 = Chi2DataVar()
        mystat2 = Chi2DataVar()
        stat1, fvec1 = mystat1.calc_stat(data1, model1, staterror1)
        stat2, fvec2 = mystat2.calc_stat(data2, model2, staterror2)
        fvec = numpy.power((data - model) / staterror, 2)
        stat = numpy.sum(fvec)
        # print stat1 + stat2 - stat
        return (stat, fvec)
        return (stat1 + stat2, numpy.append(fvec1, fvec2))
    """

    # This is based on the original code, but it's not 100% clear
    # why some of the values are being calculated.
    #
    def my_simulstat(self, data, model, *args, **kwargs):

        tofit = data.to_fit(staterrfunc=self.calc_staterror)
        modeldata = data.eval_model_to_fit(model)

        fitdata = tofit[0]
        staterror = tofit[1]

        fvec = numpy.power((fitdata - modeldata) / staterror, 2)
        stat = numpy.sum(fvec)

        mstat = 0.0
        mfvec = []

        # It is not clear what separating the data sets does
        # here, based on the original my_simulsat code.
        #
        stats = [Chi2DataVar(), Chi2DataVar()]
        for mystat, dset, mexpr in zip(stats, data.datasets, model.parts):

            thisstat, thisvec = mystat.calc_stat(dset, mexpr)
            mstat += thisstat
            mfvec.append(thisvec)

        # return (mstat, numpy.concatenate(mfvec))
        return (stat, fvec)

    calc_stat = my_simulstat
    calc_staterror = mycal_staterror


class MyCashWithBkg(UserStat):

    def __init__(self, name='mycash'):
        UserStat.__init__(self, name)

    @staticmethod
    def mycal_staterror(data):
        return None

    """
    @staticmethod
    def cash_withbkg(data, model, staterror, *args, **kwargs):
        fvec = model - (data * numpy.log(model))
        weight = kwargs.get('weight')
        if weight is not None:
            fvec = fvec * weight
        return 2.0 * sum(fvec), fvec
    """

    @staticmethod
    def cash_withbkg(data, model, *args, **kwargs):

        tofit = data.to_fit(staterrfunc=None)
        modeldata = data.eval_model_to_fit(model)

        fitdata = tofit[0]
        fvec = modeldata - (fitdata  * numpy.log(modeldata))
        weight = kwargs.get('weight')
        if weight is not None:
            fvec = fvec * weight

        return 2.0 * fvec.sum(), fvec

    calc_stat = cash_withbkg
    calc_staterror = mycal_staterror


class MyChiWithBkg(UserStat):

    def __init__(self, name='mychi'):
        UserStat.__init__(self, name)

    @staticmethod
    def mycal_staterror(data):
        return numpy.ones_like(data)

    """
    @staticmethod
    def chi_withbkg(data, model, staterror, *args, **kwargs):
        fvec = ((data - model) / staterror)**2
        stat = fvec.sum()
        return (stat, fvec)
    """

    def chi_withbkg(self, data, model, *args, **kwargs):

        tofit = data.to_fit(staterrfunc=self.calc_staterror)
        modeldata = data.eval_model_to_fit(model)

        fitdata = tofit[0]
        staterror = tofit[1]

        fvec = ((fitdata - modeldata) / staterror)**2
        return fvec.sum(), fvec

    calc_stat = chi_withbkg
    calc_staterror = mycal_staterror


class MyCashNoBkg(UserStat):

    def __init__(self, name='mycash'):
        UserStat.__init__(self, name)

    @staticmethod
    def mycal_staterror(data):
        return None

    """
    @staticmethod
    def cash_nobkg(data, model, staterror, *args, **kwargs):
        fvec = model - (data * numpy.log(model))
        weight = kwargs.get('weight')
        if weight is not None:
            fvec = fvec * weight
        return 2.0 * sum(fvec), fvec
    """

    @staticmethod
    def cash_nobkg(data, model, *args, **kwargs):

        tofit = data.to_fit(staterrfunc=None)
        modeldata = data.eval_model_to_fit(model)

        fitdata = tofit[0]
        fvec = modeldata - (fitdata  * numpy.log(modeldata))
        weight = kwargs.get('weight')
        if weight is not None:
            fvec = fvec * weight

        return 2.0 * fvec.sum(), fvec

    calc_stat = cash_nobkg
    calc_staterror = mycal_staterror


class MyChiNoBkg(UserStat):

    def __init__(self, name='mychi'):
        UserStat.__init__(self, name)

    @staticmethod
    def mycal_staterror(data):
        return numpy.ones_like(data)

    """
    @staticmethod
    def chi_nobkg(data, model, staterror, *args, **kwargs):
        fvec = ((data - model) / staterror)**2
        stat = fvec.sum()
        return (stat, fvec)
    """

    def chi_nobkg(self, data, model, *args, **kwargs):

        tofit = data.to_fit(staterrfunc=self.calc_staterror)
        modeldata = data.eval_model_to_fit(model)

        fitdata = tofit[0]
        staterror = tofit[1]

        fvec = ((fitdata - modeldata) / staterror)**2
        return fvec.sum(), fvec

    calc_stat = chi_nobkg
    calc_staterror = mycal_staterror


@pytest.fixture
def reset_xspec():

    from sherpa.astro import xspec

    # Ensure we have a known set of XSPEC settings.
    # At present this is just the abundance and cross-section,
    # since the cosmology settings do not affect any of the
    # models used here.
    #
    abund = xspec.get_xsabund()
    xsect = xspec.get_xsxsect()

    xspec.set_xsabund('angr')
    xspec.set_xsxsect('bcmc')

    yield

    xspec.set_xsabund(abund)
    xspec.set_xsxsect(xsect)


@pytest.fixture
def setup(make_data_path):

    from sherpa.astro.io import read_pha
    from sherpa.astro import xspec

    pha_fname = make_data_path("9774.pi")
    data = read_pha(pha_fname)
    data.notice(0.5, 7.0)

    abs1 = xspec.XSphabs('abs1')
    p1 = PowLaw1D('p1')
    model = abs1 + p1

    return {'data': data, 'model': model}


@pytest.fixture
def setup_bkg(make_data_path):

    from sherpa.astro.io import read_pha
    from sherpa.astro import xspec

    bkg_fname = make_data_path("9774_bg.pi")
    # bkg.notice(0.5, 7.0)
    bkg = read_pha(bkg_fname)

    abs1 = xspec.XSphabs('abs1')
    p1 = PowLaw1D('p1')
    model = abs1 + p1

    return {'bkg': bkg, 'model': model}


@pytest.fixture
def setup_two(make_data_path):

    from sherpa.astro.io import read_pha
    from sherpa.astro import xspec

    abs1 = xspec.XSphabs('abs1')
    p1 = PowLaw1D('p1')
    model = abs1 + p1

    model_mult = abs1 * p1

    pi2278 = make_data_path("pi2278.fits")
    pi2286 = make_data_path("pi2286.fits")
    data_pi2278 = read_pha(pi2278)
    data_pi2286 = read_pha(pi2286)

    return {'data_pi2278': data_pi2278, 'data_pi2286': data_pi2286,
            'model_mult': model_mult}


def compare_results(arg1, arg2, tol=1e-6):

    for key in ["succeeded", "numpoints", "dof"]:
        assert arg1[key] == int(getattr(arg2, key))

    for key in ["istatval", "statval"]:
        val = float(getattr(arg2, key))
        assert val == pytest.approx(arg1[key])

    # TODO: may have to add tolerance?
    assert arg2.parvals == pytest.approx(arg1['parvals'])


@requires_fits
@requires_xspec
@requires_data
def test_chi2xspecvar_stat(hide_logging, reset_xspec, setup):
    fit = Fit(setup['data'], setup['model'], Chi2XspecVar(), NelderMead())
    results = fit.fit()

    _fit_chi2xspecvar_results_bench = {
        'succeeded': 1,
        'numpoints': 446,
        'dof': 443,
        'istatval': 3488.58436522,
        'statval': 1167.11621982,
        'parnames': ('abs1.nH', 'abs1.gamma', 'abs1.ampl'),
        'parvals': numpy.array(
            [4717.3082876288863, 1.785895698907098, 39702.914274813716])
    }

    compare_results(_fit_chi2xspecvar_results_bench, results)


@requires_fits
@requires_xspec
@requires_data
def test_chi2modvar_stat(hide_logging, reset_xspec, setup):
    fit = Fit(setup['data'], setup['model'], Chi2ModVar(), NelderMead())
    results = fit.fit()

    _fit_chi2modvar_results_bench = {
        'succeeded': 1,
        'numpoints': 446,
        'dof': 443,
        'istatval': 98751.1141165,
        'statval': 951.052518517,
        'parnames': ('abs1.nH', 'abs1.gamma', 'abs1.ampl'),
        'parvals': numpy.array(
            [6323.954237402093, 1.5898717247339578, 25049.100925267721])
    }

    compare_results(_fit_chi2modvar_results_bench, results)


@requires_fits
@requires_xspec
@requires_data
def test_chi2constvar_stat(hide_logging, reset_xspec, setup):
    fit = Fit(setup['data'], setup['model'], Chi2ConstVar(), LevMar())
    results = fit.fit()

    _fit_chi2constvar_results_bench = {
        'succeeded': 1,
        'numpoints': 446,
        'dof': 443,
        'istatval': 11078.2610904,
        'statval': 1664.80903,
        'parnames': ('abs1.nH', 'abs1.gamma', 'abs1.ampl'),
        'parvals': numpy.array(
            [473.75459019175156, 1.2169817123652888, 4487.1266712927545])
    }

    compare_results(_fit_chi2constvar_results_bench, results)


@requires_fits
@requires_xspec
@requires_data
def test_chi2gehrels_stat(hide_logging, reset_xspec, setup):
    fit = Fit(setup['data'], setup['model'], Chi2Gehrels(), NelderMead())
    results = fit.fit()

    _fit_chi2gehrels_results_bench = {
        'succeeded': 1,
        'numpoints': 446,
        'dof': 443,
        'istatval': 2295.18738409,
        'statval': 590.888903039,
        'parnames': ('abs1.nH', 'abs1.gamma', 'abs1.ampl'),
        'parvals': numpy.array(
            [5077.8010218337085, 1.592875823400443, 19067.111802328174])
    }

    compare_results(_fit_chi2gehrels_results_bench, results)


@requires_fits
@requires_xspec
@requires_data
def test_leastsq_stat(hide_logging, reset_xspec, setup):
    fit = Fit(setup['data'], setup['model'], LeastSq(), LevMar())
    results = fit.fit()

    _fit_leastsq_results_bench = {
        'succeeded': 1,
        'numpoints': 446,
        'dof': 443,
        'istatval': 100275.650273,
        'statval': 15069.134653,
        'parnames': ('abs1.nH', 'abs1.gamma', 'abs1.ampl'),
        'parvals': numpy.array(
            [  4.737546e+02,   1.216982e+00,   4.487127e+03])
    }

    compare_results(_fit_leastsq_results_bench, results)


@requires_fits
@requires_xspec
@requires_data
def test_cstat_stat(hide_logging, reset_xspec, setup):
    fit = Fit(setup['data'], setup['model'], CStat(), NelderMead())
    results = fit.fit()

    _fit_cstat_results_bench = {
        'succeeded': 1,
        'numpoints': 446,
        'dof': 443,
        'istatval': 16859.677457,
        'statval': 1173.95573689,
        'parnames': ('abs1.nH', 'abs1.gamma', 'abs1.ampl'),
        'parvals': numpy.array(
            [5886.0660236942495, 1.6556198746259132, 30098.968589487202])
    }

    compare_results(_fit_cstat_results_bench, results)


@requires_fits
@requires_xspec
@requires_data
@pytest.mark.parametrize('stat', [Cash, MyCashWithBkg, MyCashNoBkg])
def test_cash_stat(stat, hide_logging, reset_xspec, setup):
    fit = Fit(setup['data'], setup['model'], stat(), NelderMead())
    results = fit.fit()

    _fit_mycash_results_bench = {
        'succeeded': 1,
        'numpoints': 446,
        'dof': 443,
        'istatval': 796.401435754,
        'statval': -14889.3202844,
        'parnames': ('abs1.nH', 'abs1.gamma', 'abs1.ampl'),
        'parvals': numpy.array(
            [5886.0660236942495, 1.6556198746259132, 30098.968589487202])
    }

    compare_results(_fit_mycash_results_bench, results)


_fit_mychi_results_bench = {
    'succeeded': 1,
    'numpoints': 446,
    'dof': 443,
    'istatval': 100275.650273,
    'statval': 15082.4817361,
    'parnames': ('abs1.nH', 'abs1.gamma', 'abs1.ampl'),
    'parvals': numpy.array(
        [65.215835020062741, 1.2149346471169165, 4454.4695930173866])
    }


@requires_fits
@requires_xspec
@requires_data
def test_mychi_data_and_model_have_bkg(hide_logging, reset_xspec, setup):
    fit = Fit(setup['data'], setup['model'], MyChiWithBkg(), LevMar())
    results = fit.fit()

    compare_results(_fit_mychi_results_bench, results)


@requires_fits
@requires_xspec
@requires_data
@pytest.mark.parametrize('stat', [MyCashNoBkg, MyCashWithBkg])
def test_mycash_data_and_model_donothave_bkg(stat, hide_logging, reset_xspec, setup_bkg):
    fit = Fit(setup_bkg['bkg'], setup_bkg['model'], stat(), NelderMead())
    results = fit.fit()

    _fit_mycashnobkg_results_bench = {
        'succeeded': 1,
        'numpoints': 1024,
        'dof': 1021,
        'istatval': 2198.3631781,
        'statval': 1716.74869273,
        'parnames': ('abs1.nH', 'abs1.gamma', 'abs1.ampl'),
        'parvals': numpy.array(
            [295.11120384933781, 0.69990055680397523, 20.998971817852862])
    }

    compare_results(_fit_mycashnobkg_results_bench, results,
                    tol=1.0e-3)


@requires_fits
@requires_xspec
@requires_data
@pytest.mark.parametrize('stat', [MyChiNoBkg, MyChiWithBkg])
def test_mychi_data_and_model_donothave_bkg(stat, hide_logging, reset_xspec, setup_bkg):
    fit = Fit(setup_bkg['bkg'], setup_bkg['model'], stat(), LevMar())
    results = fit.fit()

    _fit_mychinobkg_results_bench = {
        'succeeded': 1,
        'numpoints': 1024,
        'dof': 1021,
        'istatval': 5664.2486547,
        'statval': 7928.05674899,
        'parnames': ('abs1.nH', 'abs1.gamma', 'abs1.ampl'),
        'parvals': numpy.array(
            [346.51084808235697, 0.24721168701021015, 7.9993714921823997])
    }

    compare_results(_fit_mychinobkg_results_bench, results, 1e-5)


@requires_fits
@requires_xspec
@requires_data
def test_mychi_datahasbkg_modelhasnobkg(hide_logging, reset_xspec, setup):
    fit = Fit(setup['data'], setup['model'], MyChiNoBkg(), LevMar())
    results = fit.fit()

    compare_results(_fit_mychi_results_bench, results)


@requires_fits
@requires_xspec
@requires_data
def test_wstat(hide_logging, reset_xspec, setup):

    fit = Fit(setup['data'], setup['model'], WStat(), LevMar())
    results = fit.fit()

    _fit_wstat_results_bench = {
        'succeeded': 1,
        'numpoints': 446,
        'dof': 443,
        'istatval': 14000.5250801,
        'statval': 1157.1914764381368,
        'rstat': 2.6107833248,
        'parnames': ('abs1.nH', 'abs1.gamma', 'abs1.ampl'),
        'parvals': numpy.array(
            [  2.675400e+03,   1.656894e+00,   2.976256e+04])
    }

    # On a local linux machine I have to bump the tolerance to
    # 3e-4, but this isn't seen on Travis. The fit isn't
    # "great", so it may be that the results are sensitive to
    # numerical differences (e.g. as introduced with updated
    # compilers).
    # tol = 3e-4
    tol = 1e-6  # TODO: investigate difference
    compare_results(_fit_wstat_results_bench, results,
                    tol=tol)


# The following test passes if run by itself but fails when run with others
# def test_wstat1(self):
#     pha_fname = self.make_path("stats/acisf09122_000N001_r0013_pha3.fits")
#     ui.load_pha(pha_fname)
#     #ui.set_analysis('energy')
#     ui.ignore(None, None)
#     ui.notice(1.0, 1.6)
#     src = ui.xsphabs.gal * ui.xspowerlaw.pl
#     gal.nh = 0.1
#     pl.phoindex = 0.7
#     pl.norm = 1e-4
#     ui.set_source(src)
#     ui.set_stat('wstat')
#     assert numpy.allclose(46.455049531, ui.calc_stat(), 1.e-7, 1.e-7)


@requires_fits
@requires_xspec
@requires_data
def test_wstat_error(hide_logging, reset_xspec, setup_bkg):
    fit = Fit(setup_bkg['bkg'], setup_bkg['model'], WStat(), NelderMead())

    with pytest.raises(StatErr):
        fit.fit()


def test_chi2datavar(hide_logging):
    num = 3
    xy = numpy.array(range(num))
    ui.load_arrays(1, xy, xy, Data1D)
    ui.set_stat('chi2datavar')
    err = ui.get_staterror()
    assert err == pytest.approx(numpy.sqrt(xy))


@requires_fits
@requires_xspec
@requires_data
def test_get_stat_info(hide_logging, make_data_path):
    fname_3c273 = make_data_path("3c273.pi")
    ui.load_pha(fname_3c273)
    src = ui.xspowerlaw.pl
    ui.set_source(src)
    ui.guess('pl')
    ui.set_stat('wstat')
    stat_info = ui.get_stat_info()[0]
    assert stat_info.dof == 44
    assert stat_info.numpoints == 46


@requires_fits
@requires_xspec
@requires_data
@pytest.mark.parametrize('stat', [MySimulStat, MyChiNoBkg])
def test_simul_stat_fit(stat, hide_logging, reset_xspec, setup_two):
    data1 = setup_two['data_pi2278']
    data2 = setup_two['data_pi2286']
    model1 = setup_two['model_mult']
    model2 = setup_two['model_mult']
    data = DataSimulFit(name='data1data2', datasets=[data1, data2])
    model = SimulFitModel(name='model1model2', parts=[model1, model2])
    fit = Fit(data=data, model=model, stat=stat(),
              method=NelderMead())
    result = fit.fit()

    _fit_simul_datavarstat_results_bench = {
        'succeeded': 1,
        'numpoints': 18,
        'dof': 15,
        'istatval': 1218.11457171,
        'statval': 204.883073969,
        'parnames': ('abs1.nH', 'abs1.gamma', 'abs1.ampl'),
        'parvals': numpy.array(
            [65647.539439194588, 2.1440354994101929, 13955.023665227312])
    }

    compare_results(_fit_simul_datavarstat_results_bench,
                    result)


@requires_data
@requires_fits
def test_wstat_calc_stat_info(hide_logging, make_data_path):
    "bug #147"
    ui.load_pha("stat", make_data_path("3c273.pi"))
    ui.set_source("stat", ui.powlaw1d.p1)
    ui.set_stat("wstat")
    ui.fit("stat")
    ui.get_stat_info()


@pytest.mark.xfail(reason='y errors are not calculated correctly')
@pytest.mark.parametrize("bexp,yexp,dyexp",
                         [(1,
                           [0, -1, -3, 1, 3, 0, -2, 2, 0],
                           [1, 1, 1.73205078, 1, 1.73205078, 1.41421354, 2, 2, 2.44948983]),
                          (10,
                           [0, -0.1, -0.3, 1, 3, 0.9, 0.7, 2.9, 2.7],
                           [0.1, 0.1, 0.173205078, 1, 1.73205078, 1.0049876, 1.01488912, 1.73493516, 1.74068952]),
                          (0.1,
                           [0, -10, -30, 1, 3, -9, -29, -7, -27],
                           [1, 10, 17.320507, 1, 1.73205078, 10.0498753, 17.3493519, 10.1488914, 17.4068947])
                          ])
def test_xspecvar_zero_handling(bexp, yexp, dyexp):
    """How does XSPEC variance handle 0 in source and/or background?

    The values were calculated using XSPEC 12.10.1m (HEASOFT 6.26.1)
    using the following commands to create the file foo.dat which
    contains (after three 'header' lines) the data 'x 0.5 y dy'

        data foo.fits
	iplot data
	wplot foo.dat
	quit

    where foo.fits is a fake PHA file set up to have the channel/count
    values used below (a CSC-style PHA file was used so that source
    and background were in the same file but a separate bgnd PHA
    file could also have been used).
    """

    stat = Chi2XspecVar()
    chans = numpy.arange(1, 10, dtype=numpy.int16)
    scnts = numpy.asarray([0, 0, 0, 1, 3, 1, 1, 3, 3], dtype=numpy.int16)
    bcnts = numpy.asarray([0, 1, 3, 0, 0, 1, 3, 1, 3], dtype=numpy.int16)

    s = DataPHA('src', chans, scnts, exposure=1)
    b = DataPHA('bkg', chans, bcnts, exposure=bexp)
    s.set_background(b)
    s.subtract()

    y, dy, other = s.to_fit(staterrfunc=stat.calc_staterror)
    assert other is None
    assert y == pytest.approx(yexp)
    assert dy == pytest.approx(dyexp)

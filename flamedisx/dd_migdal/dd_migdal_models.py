from copy import copy
import numpy as np
import tensorflow as tf

import os

from multihist import Hist1d

import scipy.interpolate as itp
from scipy import integrate

from .. import dd_migdal as fd_dd_migdal

import flamedisx as fd
export, __all__ = fd.exporter()
o = tf.newaxis

import numba as nb


@export
class NRSource(fd.BlockModelSource):
    model_blocks = (
        fd_dd_migdal.EnergySpectrumFirstSS,
        fd_dd_migdal.MakeS1S2SS)

    S2Width_dist = np.load(os.path.join(
        os.path.dirname(__file__), './migdal_database/SS_Mig_S2Width_template.npz'))

    hist_values_S2Width = S2Width_dist['hist_values']
    S2Width_edges = S2Width_dist['S2Width_edges']

    mh_S2Width = Hist1d(bins=len(S2Width_edges) - 1).from_histogram(hist_values_S2Width, bin_edges=S2Width_edges)
    mh_S2Width = mh_S2Width / mh_S2Width.n
    mh_S2Width = mh_S2Width / mh_S2Width.bin_volumes()

    S2Width_diff_rate = mh_S2Width
    S2Width_events_per_bin = mh_S2Width * mh_S2Width.bin_volumes()

    def mu_before_efficiencies(self, **params):
        return 1.

    @staticmethod
    def signal_means(energy, a=13.1895962, b=1.06532331,
                     c_s2_0=3.70318382, c_s2_1=-3.49159718, c_s2_2=0.07861683,
                     g1=0.1131, g2=47.35,
                     s1_mean_multiplier=1., s2_mean_multiplier=1.):
        P = c_s2_0 + c_s2_1 * (fd.tf_log10(energy) - 1.6) + c_s2_2 * pow((fd.tf_log10(energy) - 1.6), 2)
        s2_mean = s2_mean_multiplier * P * energy * g2

        s1_mean = s1_mean_multiplier * (a * energy**b - s2_mean / g2) * g1
        s1_mean= tf.where(s1_mean < 0.01, 0.01 * tf.ones_like(s1_mean, dtype=fd.float_type()), s1_mean)

        return s1_mean, s2_mean

    @staticmethod
    def signal_vars(*args, d_s1=1.20307136, d_s2=38.27449296):
        s1_mean = args[0]
        s2_mean = args[1]

        s1_var = d_s1 * s1_mean

        s2_var = d_s2 * s2_mean

        return s1_var, s2_var

    @staticmethod
    def signal_corr(energies, anti_corr=-0.20949764):
        return anti_corr * tf.ones_like(energies)

    def get_s2(self, s2):
        return s2

    def s1s2_acceptance(self, s1, s2, s1_min=20, s1_max=200, s2_min=400, s2_max=3e4):
        s1_acc = tf.where((s1 < s1_min) | (s1 > s1_max),
                          tf.zeros_like(s1, dtype=fd.float_type()),
                          tf.ones_like(s1, dtype=fd.float_type()))
        s2_acc = tf.where((s2 < s2_min) | (s2 > s2_max),
                          tf.zeros_like(s2, dtype=fd.float_type()),
                          tf.ones_like(s2, dtype=fd.float_type()))
        s1s2_acc = tf.where((s2 > 200*s1**(0.73)),
                            tf.ones_like(s2, dtype=fd.float_type()),
                            tf.zeros_like(s2, dtype=fd.float_type()))
        nr_endpoint = tf.where((s1 > 140) & (s2 > 8e3) & (s2 < 11.5e3),
                            tf.zeros_like(s2, dtype=fd.float_type()),
                            tf.ones_like(s2, dtype=fd.float_type()))

        return (s1_acc * s2_acc * s1s2_acc * nr_endpoint)

    final_dimensions = ('s1',)

    def pdf_for_mu_pre_populate(self, **params):
        old_defaults = copy(self.defaults)
        self.set_defaults(**params)

        s1_mean, s2_mean = self.gimme('signal_means', bonus_arg=self.energies_first)
        s1_var, s2_var = self.gimme('signal_vars', bonus_arg=(s1_mean, s2_mean))
        s1_mean = fd.tf_to_np(s1_mean)
        s2_mean = fd.tf_to_np(s2_mean)
        s1_var = fd.tf_to_np(s1_var)
        s2_var = fd.tf_to_np(s2_var)

        s1_std = np.sqrt(s1_var)
        s2_std = np.sqrt(s2_var)

        anti_corr = self.gimme('signal_corr', bonus_arg=self.energies_first)
        anti_corr = fd.tf_to_np(anti_corr)

        spectrum = fd.tf_to_np(self.rates_vs_energy_first)

        self.defaults = old_defaults

        return s1_mean, s2_mean, s1_var, s2_var, s1_std, s2_std, anti_corr, spectrum

    @staticmethod
    @nb.njit(error_model="numpy",fastmath=True)
    def pdf_for_mu(s1, s2, s1_mean, s2_mean, s1_var, s2_var, s1_std, s2_std, anti_corr, spectrum):
        denominator = 2. * np.pi * s1_std * s2_std * np.sqrt(1.- anti_corr * anti_corr)
        exp_prefactor = -1. / (2 * (1. - anti_corr * anti_corr))
        exp_term_1 = (s1 - s1_mean) * (s1 - s1_mean) / s1_var
        exp_term_2 = (s2 - s2_mean) * (s2 - s2_mean) / s2_var
        exp_term_3 = -2. * anti_corr * (s1 - s1_mean) * (s2 - s2_mean) / (s1_std * s2_std)

        pdf_vals = 1. / denominator * np.exp(exp_prefactor * (exp_term_1 + exp_term_2 + exp_term_3))

        s1s2_acc = np.where((s2 > 200*s1**(0.73)), 1., 0.)
        nr_endpoint = np.where((s1 > 140) & (s2 > 8e3) & (s2 < 11.5e3), 0., 1.)

        return np.sum(pdf_vals * s1s2_acc * nr_endpoint * spectrum)

    def estimate_mu(self, error=1e-5, **params):
        """
        """
        s1_mean, s2_mean, s1_var, s2_var, s1_std, s2_std, anti_corr, spectrum = \
            self.pdf_for_mu_pre_populate(**params)

        f = lambda s2, s1: self.pdf_for_mu(s1, s2, s1_mean, s2_mean, s1_var, s2_var,
                                           s1_std, s2_std, anti_corr, spectrum)

        return integrate.dblquad(f, self.defaults['s1_min'], self.defaults['s1_max'],
                                 self.defaults['s2_min'], self.defaults['s2_max'],
                                 epsabs=error, epsrel=error)

@export
class NRNRSource(NRSource):
    model_blocks = (
        fd_dd_migdal.EnergySpectrumFirstMSU,
        fd_dd_migdal.EnergySpectrumSecondMSU,
        fd_dd_migdal.MakeS1S2MSU)

    no_step_dimensions = ('energy_second')

    S2Width_dist = np.load(os.path.join(
        os.path.dirname(__file__), './migdal_database/MSU_IECS_S2Width_template.npz'))

    hist_values_S2Width = S2Width_dist['hist_values']
    S2Width_edges = S2Width_dist['S2Width_edges']

    mh_S2Width = Hist1d(bins=len(S2Width_edges) - 1).from_histogram(hist_values_S2Width, bin_edges=S2Width_edges)
    mh_S2Width = mh_S2Width / mh_S2Width.n
    mh_S2Width = mh_S2Width / mh_S2Width.bin_volumes()

    S2Width_diff_rate = mh_S2Width
    S2Width_events_per_bin = mh_S2Width * mh_S2Width.bin_volumes()


@export
class NRNRNRSource(NRNRSource):
    model_blocks = (
        fd_dd_migdal.EnergySpectrumFirstMSU3,
        fd_dd_migdal.EnergySpectrumOthersMSU3,
        fd_dd_migdal.MakeS1S2MSU3)

    no_step_dimensions = ('energy_others')


@export
class Migdal2Source(NRNRSource):
    model_blocks = (
        fd_dd_migdal.EnergySpectrumFirstMigdal,
        fd_dd_migdal.EnergySpectrumSecondMigdal2,
        fd_dd_migdal.MakeS1S2Migdal)

    S2Width_dist = np.load(os.path.join(
        os.path.dirname(__file__), './migdal_database/SS_Mig_S2Width_template.npz'))

    hist_values_S2Width = S2Width_dist['hist_values']
    S2Width_edges = S2Width_dist['S2Width_edges']

    mh_S2Width = Hist1d(bins=len(S2Width_edges) - 1).from_histogram(hist_values_S2Width, bin_edges=S2Width_edges)
    mh_S2Width = mh_S2Width / mh_S2Width.n
    mh_S2Width = mh_S2Width / mh_S2Width.bin_volumes()

    S2Width_diff_rate = mh_S2Width
    S2Width_events_per_bin = mh_S2Width * mh_S2Width.bin_volumes()

    ER_NEST = np.load(os.path.join(
        os.path.dirname(__file__), './migdal_database/ER_NEST.npz'))

    E_ER = ER_NEST['EkeVee']
    s1_mean_ER = itp.interp1d(E_ER, ER_NEST['s1mean'])
    s2_mean_ER = itp.interp1d(E_ER, ER_NEST['s2mean'])
    s1_var_ER = itp.interp1d(E_ER, ER_NEST['s1std']**2)
    s2_var_ER = itp.interp1d(E_ER, ER_NEST['s2std']**2)
    s1s2_corr_ER = itp.interp1d(E_ER, ER_NEST['S1S2corr'])

    def __init__(self, *args, **kwargs):
        energies_first = self.model_blocks[0].energies_first
        energies_first = tf.where(energies_first > 49., 49. * tf.ones_like(energies_first), energies_first)
        energies_first = tf.repeat(energies_first[:, o], tf.shape(self.model_blocks[1].energies_second), axis=1)

        self.s1_mean_ER_tf, self.s2_mean_ER_tf = self.signal_means_ER(energies_first)
        self.s1_var_ER_tf, self.s2_var_ER_tf, self.s1s2_cov_ER_tf = self.signal_vars_ER(energies_first)

        super().__init__(*args, **kwargs)

    def signal_means_ER(self, energy):
        energy_cap = np.where(energy <= 49., energy, 49.)
        s1_mean = tf.cast(self.s1_mean_ER(energy_cap), fd.float_type())
        s2_mean = tf.cast(self.s2_mean_ER(energy_cap), fd.float_type())

        return s1_mean, s2_mean

    def signal_vars_ER(self, energy):
        energy_cap = np.where(energy <= 49., energy, 49.)
        s1_var = tf.cast(self.s1_var_ER(energy_cap), fd.float_type())
        s2_var = tf.cast(self.s2_var_ER(energy_cap), fd.float_type())
        s1s2_corr = tf.cast(np.nan_to_num(self.s1s2_corr_ER(energy_cap)), fd.float_type())
        s1s2_cov = s1s2_corr * tf.sqrt(s1_var * s2_var)

        return s1_var, s2_var, s1s2_cov


@export
class Migdal3Source(Migdal2Source):
    model_blocks = (
        fd_dd_migdal.EnergySpectrumFirstMigdal,
        fd_dd_migdal.EnergySpectrumSecondMigdal3,
        fd_dd_migdal.MakeS1S2Migdal)


@export
class Migdal4Source(Migdal2Source):
    model_blocks = (
        fd_dd_migdal.EnergySpectrumFirstMigdal,
        fd_dd_migdal.EnergySpectrumSecondMigdal4,
        fd_dd_migdal.MakeS1S2Migdal)


@export
class MigdalMSUSource(Migdal2Source):
    model_blocks = (
        fd_dd_migdal.EnergySpectrumFirstMigdalMSU,
        fd_dd_migdal.EnergySpectrumOthersMigdalMSU,
        fd_dd_migdal.MakeS1S2MigdalMSU)

    no_step_dimensions = ('energy_others')

    S2Width_dist = np.load(os.path.join(
        os.path.dirname(__file__), './migdal_database/MSU_IECS_S2Width_template.npz'))

    hist_values_S2Width = S2Width_dist['hist_values']
    S2Width_edges = S2Width_dist['S2Width_edges']

    mh_S2Width = Hist1d(bins=len(S2Width_edges) - 1).from_histogram(hist_values_S2Width, bin_edges=S2Width_edges)
    mh_S2Width = mh_S2Width / mh_S2Width.n
    mh_S2Width = mh_S2Width / mh_S2Width.bin_volumes()

    S2Width_diff_rate = mh_S2Width
    S2Width_events_per_bin = mh_S2Width * mh_S2Width.bin_volumes()


@export
class IECSSource(Migdal2Source):
    model_blocks = (
        fd_dd_migdal.EnergySpectrumFirstIE_CS,
        fd_dd_migdal.EnergySpectrumSecondIE_CS,
        fd_dd_migdal.MakeS1S2Migdal)

    S2Width_dist = np.load(os.path.join(
        os.path.dirname(__file__), './migdal_database/MSU_IECS_S2Width_template.npz'))

    hist_values_S2Width = S2Width_dist['hist_values']
    S2Width_edges = S2Width_dist['S2Width_edges']

    mh_S2Width = Hist1d(bins=len(S2Width_edges) - 1).from_histogram(hist_values_S2Width, bin_edges=S2Width_edges)
    mh_S2Width = mh_S2Width / mh_S2Width.n
    mh_S2Width = mh_S2Width / mh_S2Width.bin_volumes()

    S2Width_diff_rate = mh_S2Width
    S2Width_events_per_bin = mh_S2Width * mh_S2Width.bin_volumes()

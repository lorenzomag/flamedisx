"""Background sources for LXe TPCs

"""
import tensorflow as tf

import os
import numpy as np
import pandas as pd

import flamedisx as fd
from . import lxe_sources as fd_nest

export, __all__ = fd.exporter()


##
# Flamedisx sources
##


@export
class vERSource(fd_nest.nestERSource):
    """ER background source from solar neutrinos (PP+7Be+CNO).
    Reads in energy spectrum from .pkl file, generated with LZ's DMCalc.
    Normalise such that the spectrum predicts 30.759 events in 1 tonne year.
    """

    def __init__(self, *args, fid_mass=1., livetime=1., **kwargs):
        if ('detector' not in kwargs):
            kwargs['detector'] = 'default'

        df_vER = pd.read_pickle(os.path.join(os.path.dirname(__file__), 'background_spectra/vER_spectrum_scan.pkl'))

        self.energies = tf.convert_to_tensor(df_vER['energy_keV'].values, dtype=fd.float_type())
        scale = fid_mass * livetime * 55.440
        self.rates_vs_energy = tf.convert_to_tensor(df_vER['spectrum_value_norm'].values * scale, dtype=fd.float_type())

        super().__init__(*args, **kwargs)


@export
class vNRSolarSource(fd_nest.nestNRSource):
    """CEvNS background source from B8 + HEP neutrinos.
    Reads in energy spectrum from .pkl file, generated with LZ's DMCalc.
    Normalise such that the spectrum predicts 123.675 events in 1 tonne year.
    """

    def __init__(self, *args, fid_mass=1., livetime=1., **kwargs):
        if ('detector' not in kwargs):
            kwargs['detector'] = 'default'

        df_CEvNS_solar = pd.read_pickle(os.path.join(os.path.dirname(__file__), 'background_spectra/CEvNS_solar_spectrum_scan.pkl'))

        self.energies = tf.convert_to_tensor(df_CEvNS_solar['energy_keV'].values, dtype=fd.float_type())
        scale = fid_mass * livetime * 754.914
        self.rates_vs_energy = tf.convert_to_tensor(df_CEvNS_solar['spectrum_value_norm'].values * scale, dtype=fd.float_type())

        super().__init__(*args, **kwargs)


@export
class vNROtherSource(fd_nest.nestNRSource):
    """CEvNS background source from Atmospheric + DSNB neutrinos.
    Reads in energy spectrum from .pkl file, generated with LZ's DMCalc.
    Normalise such that the spectrum predicts 0.066 events in 1 tonne year.
    """

    def __init__(self, *args, fid_mass=1., livetime=1., **kwargs):
        if ('detector' not in kwargs):
            kwargs['detector'] = 'default'

        df_CEvNS_other = pd.read_pickle(os.path.join(os.path.dirname(__file__), 'background_spectra/CEvNS_other_spectrum_scan.pkl'))

        self.energies = tf.convert_to_tensor(df_CEvNS_other['energy_keV'].values, dtype=fd.float_type())
        scale = fid_mass * livetime * 0.079
        self.rates_vs_energy = tf.convert_to_tensor(df_CEvNS_other['spectrum_value_norm'].values * scale, dtype=fd.float_type())

        super().__init__(*args, **kwargs)

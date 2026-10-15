"""Check the FAO-56 ET0 implementation against the worked example in the FAO-56 paper (Example 18):
Brussels, 6 July: Tmax 21.5, Tmin 12.3, RHmax 84, RHmin 63, u2 = 2.078 m/s, Rs = 22.07 MJ/m2/day,
lat 50.80 N, elevation 100 m, day 187. Published ET0 = 3.88 mm/day.
"""
import numpy as np

from cropadvisor.et0 import (et0_penman_monteith, sat_vapour_pressure,
                             extraterrestrial_radiation, wind_10m_to_2m)


def _fao_ea():
    # FAO-56 eq. 17 (uses RHmax and RHmin) -> 1.409 kPa in the worked example
    return (sat_vapour_pressure(12.3) * 84 / 100 + sat_vapour_pressure(21.5) * 63 / 100) / 2


def test_extraterrestrial_radiation_example():
    # FAO-56 Example 8: lat 20 S, 3 Sept (day 246) -> Ra = 32.2 MJ/m2/day
    assert abs(extraterrestrial_radiation(-20.0, 246) - 32.2) < 0.1


def test_et0_matches_fao_worked_example():
    et0 = et0_penman_monteith(21.5, 12.3, 73.5, 2.078, 22.07, 50.80, 100, 187, ea=_fao_ea())
    assert abs(et0 - 3.88) < 0.05


def test_et0_with_mean_humidity_close_to_example():
    # Using the RHmean shortcut (eq. 19) is slightly less exact but should stay close
    et0 = et0_penman_monteith(21.5, 12.3, 73.5, 2.078, 22.07, 50.80, 100, 187)
    assert abs(et0 - 3.88) < 0.3


def test_wind_conversion_example():
    # FAO-56 Example 14: 3.2 m/s at 10 m -> about 2.4 m/s at 2 m
    assert abs(wind_10m_to_2m(3.2) - 2.4) < 0.05


def test_array_input_works():
    doy = np.array([180, 181, 182])
    out = et0_penman_monteith(np.array([32.0, 33, 31]), np.array([24.0, 24, 23]),
                              np.array([70.0, 65, 80]), np.array([2.0, 2.5, 1.5]),
                              np.array([20.0, 22, 15]), 18.4, 636, doy)
    assert out.shape == (3,) and np.all(out > 0) and np.all(out < 10)

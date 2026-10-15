import pandas as pd

from cropadvisor.soil import (depth_weighted, parse_soilgrids, saxton_rawls, soil_summary,
                              usda_texture)


def test_saxton_rawls_matches_published_table():
    # Saxton & Rawls (2006) Table 3, OM 2.5%: (sand, clay) -> (wilting point %, field capacity %)
    table = {"loam": (40, 20, 14, 28), "clay": (25, 50, 30, 42), "sandy loam": (65, 10, 8, 18),
             "clay loam": (35, 34, 22, 36), "silt loam": (20, 15, 11, 31)}
    for name, (sand, clay, wp_pct, fc_pct) in table.items():
        fc, wp = saxton_rawls(sand, clay, 2.5)
        assert abs(wp * 100 - wp_pct) <= 1.0, name
        assert abs(fc * 100 - fc_pct) <= 1.5, name


def test_saxton_rawls_clay_holds_more_water_at_wilting():
    _, wp_clay = saxton_rawls(20, 50, 1.5)
    _, wp_sand = saxton_rawls(85, 5, 1.5)
    assert wp_clay > wp_sand


def test_usda_texture_classes():
    assert usda_texture(40, 40, 20) == "loam"
    assert usda_texture(20, 25, 55) == "clay"
    assert usda_texture(90, 5, 5) == "sand"
    assert usda_texture(10, 60, 30) == "silty clay loam"
    assert usda_texture(65, 25, 10) == "sandy loam"


SAMPLE = {"properties": {"layers": [
    {"name": "clay", "unit_measure": {"d_factor": 10},
     "depths": [{"label": "0-5cm", "values": {"mean": 500}},
                {"label": "5-15cm", "values": {"mean": 520}},
                {"label": "15-30cm", "values": {"mean": 540}}]},
    {"name": "sand", "unit_measure": {"d_factor": 10},
     "depths": [{"label": "0-5cm", "values": {"mean": 200}},
                {"label": "5-15cm", "values": {"mean": 190}},
                {"label": "15-30cm", "values": {"mean": 180}}]},
    {"name": "silt", "unit_measure": {"d_factor": 10},
     "depths": [{"label": "0-5cm", "values": {"mean": 300}},
                {"label": "5-15cm", "values": {"mean": 290}},
                {"label": "15-30cm", "values": {"mean": 280}}]},
    {"name": "soc", "unit_measure": {"d_factor": 10},
     "depths": [{"label": "0-5cm", "values": {"mean": 80}},
                {"label": "5-15cm", "values": {"mean": 60}},
                {"label": "15-30cm", "values": {"mean": None}}]},
    {"name": "phh2o", "unit_measure": {"d_factor": 10},
     "depths": [{"label": "0-5cm", "values": {"mean": 78}}]},
]}}


def test_parse_converts_units():
    df = parse_soilgrids(SAMPLE)
    clay = df[(df.property == "clay_pct") & (df.depth == "0-5cm")].value.item()
    assert clay == 50.0
    assert df[df.property == "ph"].value.item() == 7.8


def test_depth_weighting_uses_layer_thickness():
    p = depth_weighted(parse_soilgrids(SAMPLE))
    # clay: (50*5 + 52*10 + 54*15) / 30 = 52.67
    assert abs(p["clay_pct"] - 52.667) < 0.01
    # soc ignores the missing deepest layer: (8*5 + 6*10) / 15
    assert abs(p["soc_g_kg"] - 6.667) < 0.01


def test_summary_for_black_soil_like_profile():
    s = soil_summary(parse_soilgrids(SAMPLE))
    assert s["texture"] == "clay"
    assert s["field_capacity"] > s["wilting_point"] > 0
    assert 50 < s["awc_mm_per_m"] < 250

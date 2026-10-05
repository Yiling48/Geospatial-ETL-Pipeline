import pandas as pd

from src.geospatial_etl import (
    extract_city_from_text,
    in_taiwan,
    infer_city_from_series,
    normalize_addr,
)


def test_normalize_addr_removes_parenthetical_text():
    assert normalize_addr("新北市板橋區文化路一段1號（3樓）") == "新北市板橋區文化路一段1號"


def test_normalize_addr_normalizes_tai_character():
    assert normalize_addr("台北市中正區忠孝東路1號") == "臺北市中正區忠孝東路1號"


def test_extract_city_from_text_accepts_tai_variant():
    assert extract_city_from_text("台北市信義區市府路1號") == "臺北市"


def test_infer_city_from_series():
    series = pd.Series([
        "新北市板橋區文化路1號",
        "新北市新莊區中正路2號",
        "臺北市信義區市府路1號",
    ])
    assert infer_city_from_series(series) == "新北市"


def test_in_taiwan():
    assert in_taiwan(25.0330, 121.5654)
    assert not in_taiwan(35.0, 139.0)

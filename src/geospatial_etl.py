import argparse
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple

import geocoder
import pandas as pd
from geopy.geocoders import Nominatim


CITY_LIST = [
    "臺北市", "臺中市", "基隆市", "臺南市", "高雄市", "新北市", "宜蘭縣", "桃園市",
    "嘉義市", "新竹縣", "苗栗縣", "南投縣", "彰化縣", "新竹市", "雲林縣",
    "嘉義縣", "屏東縣", "花蓮縣", "臺東縣", "金門縣", "澎湖縣", "連江縣",
]

CITY_PATTERNS = [c.replace("臺", "(臺|台)") for c in CITY_LIST]
CITY_REGEX = re.compile("|".join(CITY_PATTERNS))

TW_LAT_MIN, TW_LAT_MAX = 21.0, 26.5
TW_LNG_MIN, TW_LNG_MAX = 119.0, 123.8

TW_VILLAGE_KEYS = (
    "village",
    "city_district",
    "quarter",
    "neighbourhood",
    "suburb",
    "residential",
    "locality",
    "hamlet",
    "town",
)


def normalize_addr(address: str) -> str:
    """Normalize a Taiwan address before geocoding."""
    if not isinstance(address, str):
        return ""

    address = address.replace("台", "臺").strip()
    match = re.search(r".*?號", address)
    base = match.group(0) if match else address
    return re.sub(r"（.*?）|\(.*?\)", "", base).strip()


def extract_city_from_text(address: str) -> Optional[str]:
    """Extract a Taiwan city/county name from address text."""
    if not isinstance(address, str):
        return None

    match = CITY_REGEX.search(address)
    if not match:
        return None

    return match.group(0).replace("台", "臺")


def infer_city_from_series(series: pd.Series, sample_k: int = 300) -> Optional[str]:
    """Infer the most common city/county from a sample of addresses."""
    counts: Dict[str, int] = {}

    for idx, value in enumerate(series.dropna()):
        city = extract_city_from_text(str(value))
        if city:
            counts[city] = counts.get(city, 0) + 1
        if idx + 1 >= sample_k:
            break

    if not counts:
        return None

    return max(counts.items(), key=lambda item: item[1])[0]


def in_taiwan(lat, lng) -> bool:
    """Practical coordinate sanity check for Taiwan and offshore islands."""
    try:
        lat = float(lat)
        lng = float(lng)
    except (TypeError, ValueError):
        return False

    return TW_LAT_MIN <= lat <= TW_LAT_MAX and TW_LNG_MIN <= lng <= TW_LNG_MAX


def arcgis_forward(query: str, timeout: int = 30) -> Tuple[Optional[float], Optional[float]]:
    """Forward-geocode an address with ArcGIS."""
    result = geocoder.arcgis(query, timeout=timeout)
    if result and result.ok and result.latlng:
        return result.latlng[0], result.latlng[1]
    return None, None


def _is_village_like(name: str) -> bool:
    if not name:
        return False

    name = str(name).strip()

    if re.search(r"(路|街|巷|號|段|樓|弄|社區)$", name):
        return False

    return bool(re.search(r"(里|村)$", name))


def _first_village_from_text(address_text: str) -> Optional[str]:
    parts = re.split(r"[,\s，、;；]+", address_text or "")

    for part in parts:
        part = part.strip().strip('\"\'「」()（）')
        if _is_village_like(part):
            return part

    return None


def pick_tw_village(location) -> Tuple[Optional[str], Optional[str]]:
    """Extract a Taiwan village/里/村 name from a Nominatim result."""
    if not location:
        return None, None

    address_text = location.address or ""
    address_dict = (location.raw or {}).get("address", {}) or {}

    candidates = []

    for key in TW_VILLAGE_KEYS:
        value = address_dict.get(key)

        if _is_village_like(value):
            try:
                position = address_text.find(str(value))
                if position < 0:
                    position = 10**9
            except Exception:
                position = 10**9

            candidates.append((key, str(value), position))

    if candidates:
        candidates.sort(key=lambda item: (TW_VILLAGE_KEYS.index(item[0]), item[2]))
        return address_text, candidates[0][1]

    return address_text, _first_village_from_text(address_text)


@dataclass
class GeospatialETL:
    address_col: str
    town_col: Optional[str] = None
    target_col: Optional[str] = None
    target_exclude: Optional[str] = None
    fallback_city: Optional[str] = None
    arcgis_sleep: float = 0.6
    nominatim_sleep: float = 1.2
    user_agent: str = "tw-village-pipeline"

    forward_cache: Dict[str, Tuple[Optional[float], Optional[float]]] = field(
        default_factory=dict
    )
    reverse_cache: Dict[Tuple[float, float], Tuple[Optional[str], Optional[str]]] = field(
        default_factory=dict
    )

    def __post_init__(self):
        self.nominatim = Nominatim(user_agent=self.user_agent, timeout=10)

    def reverse_geocode(self, lat: float, lng: float):
        try:
            location = self.nominatim.reverse(
                (lat, lng),
                language="zh-TW",
                addressdetails=True,
                zoom=18,
            )
            if location:
                return pick_tw_village(location)
        except Exception:
            pass

        return None, None

    def build_query_address(self, row: pd.Series, auto_city: Optional[str]) -> str:
        raw_address = str(row.get(self.address_col, "") or "").strip()
        town = (
            str(row.get(self.town_col, "") or "").strip()
            if self.town_col
            else ""
        )

        if not raw_address:
            return ""

        if extract_city_from_text(raw_address):
            query_address = raw_address
        else:
            query_address = f"{auto_city or self.fallback_city or ''}{town}{raw_address}"

        return normalize_addr(query_address)

    def should_skip_row(self, row: pd.Series) -> bool:
        if not self.target_col or self.target_exclude is None:
            return False

        return str(row.get(self.target_col, "") or "").strip() == str(
            self.target_exclude
        ).strip()

    def process_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.address_col not in df.columns:
            raise ValueError(f"Missing required address column: {self.address_col}")

        if self.town_col and self.town_col not in df.columns:
            raise ValueError(f"Missing town column: {self.town_col}")

        if self.target_col and self.target_col not in df.columns:
            raise ValueError(f"Missing target column: {self.target_col}")

        result = df.copy()

        for column in ["lat", "lng", "nomi_address", "里"]:
            if column not in result.columns:
                result[column] = pd.NA

        auto_city = infer_city_from_series(result[self.address_col]) or self.fallback_city

        for row_index, row in result.iterrows():
            try:
                if self.should_skip_row(row):
                    continue

                query_address = self.build_query_address(row, auto_city)
                if not query_address:
                    continue

                if query_address in self.forward_cache:
                    lat, lng = self.forward_cache[query_address]
                else:
                    lat, lng = arcgis_forward(query_address)
                    self.forward_cache[query_address] = (lat, lng)
                    time.sleep(self.arcgis_sleep)

                if not in_taiwan(lat, lng):
                    continue

                result.at[row_index, "lat"] = lat
                result.at[row_index, "lng"] = lng

                key = (round(float(lat), 6), round(float(lng), 6))

                if key in self.reverse_cache:
                    reverse_address, village = self.reverse_cache[key]
                else:
                    reverse_address, village = self.reverse_geocode(lat, lng)
                    self.reverse_cache[key] = (reverse_address, village)
                    time.sleep(self.nominatim_sleep)

                if reverse_address:
                    result.at[row_index, "nomi_address"] = reverse_address

                if village:
                    result.at[row_index, "里"] = village

                print(
                    f"[{row_index}] {query_address} -> "
                    f"{float(lat):.6f},{float(lng):.6f} | 里: {village or '—'}"
                )

            except Exception as exc:
                print(f"[ERROR] Row {row_index}: {exc}")
                continue

        return result


def read_csv_with_fallback(path: str) -> pd.DataFrame:
    try:
        return pd.read_csv(path, encoding="utf-8")
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="utf-8-sig")


def build_failure_tables(
    df: pd.DataFrame,
    address_col: str,
    source_file: Optional[str] = None,
    village_col: str = "里",
):
    def blank(series: pd.Series) -> pd.Series:
        as_text = series.astype(str).str.strip()
        return (
            series.isna()
            | as_text.eq("")
            | as_text.str.lower().isin(["nan", "none"])
        )

    for column in ["lat", "lng", village_col]:
        if column not in df.columns:
            df[column] = pd.NA

    geocode_fail = df[blank(df["lat"]) | blank(df["lng"])].copy()

    village_fail = df[
        ~blank(df["lat"])
        & ~blank(df["lng"])
        & blank(df[village_col])
    ].copy()

    def summarize(block: pd.DataFrame) -> pd.DataFrame:
        if block.empty:
            return pd.DataFrame(
                columns=["_source_file", "row_index", address_col]
            )

        block = block.copy()
        block.insert(0, "row_index", block.index)
        block.insert(0, "_source_file", source_file or "")
        return block[["_source_file", "row_index", address_col]]

    return summarize(geocode_fail), summarize(village_fail)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Geocode Taiwan addresses and enrich them with village-level data."
    )

    parser.add_argument("--input", required=True, help="Input CSV path.")
    parser.add_argument("--output", required=True, help="Output CSV path.")
    parser.add_argument("--addr-col", required=True, help="Address column name.")
    parser.add_argument("--town-col", default=None, help="Town/district column name.")
    parser.add_argument("--target-col", default=None, help="Optional filtering column.")
    parser.add_argument(
        "--target-exclude",
        default=None,
        help="Skip rows whose target column matches this value.",
    )
    parser.add_argument("--fallback-city", default=None)
    parser.add_argument("--arcgis-sleep", type=float, default=0.6)
    parser.add_argument("--nominatim-sleep", type=float, default=1.2)
    parser.add_argument(
        "--failure-dir",
        default=None,
        help="Optional directory for failure summary CSV files.",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    df = read_csv_with_fallback(args.input)

    pipeline = GeospatialETL(
        address_col=args.addr_col,
        town_col=args.town_col,
        target_col=args.target_col,
        target_exclude=args.target_exclude,
        fallback_city=args.fallback_city,
        arcgis_sleep=args.arcgis_sleep,
        nominatim_sleep=args.nominatim_sleep,
    )

    result = pipeline.process_dataframe(df)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_path, encoding="utf-8-sig", index=False)

    print(f"[INFO] Output: {output_path}")

    if args.failure_dir:
        failure_dir = Path(args.failure_dir)
        failure_dir.mkdir(parents=True, exist_ok=True)

        geocode_fail, village_fail = build_failure_tables(
            result,
            address_col=args.addr_col,
            source_file=Path(args.input).name,
        )

        geocode_fail.to_csv(
            failure_dir / "geocode_fail.csv",
            index=False,
            encoding="utf-8-sig",
        )
        village_fail.to_csv(
            failure_dir / "village_fail.csv",
            index=False,
            encoding="utf-8-sig",
        )


if __name__ == "__main__":
    main()

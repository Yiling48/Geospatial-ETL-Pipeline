import argparse
from pathlib import Path

import pandas as pd


def is_blank(series: pd.Series) -> pd.Series:
    as_text = series.astype(str).str.strip()
    return (
        series.isna()
        | as_text.eq("")
        | as_text.str.lower().isin(["nan", "none"])
    )


def detect_village_col(df: pd.DataFrame):
    for column in ["村里", "里"]:
        if column in df.columns:
            return column
    return None


def scan_file(path: Path, address_col: str, target_col: str, target_exclude: str):
    try:
        df = pd.read_csv(path, encoding="utf-8")
    except UnicodeDecodeError:
        df = pd.read_csv(path, encoding="utf-8-sig")

    for column in [address_col, "lat", "lng", target_col]:
        if column not in df.columns:
            df[column] = pd.NA

    village_col = detect_village_col(df)

    if village_col is None:
        village_col = "里"
        df[village_col] = pd.NA

    filtered = df.copy()

    if target_col:
        filtered = filtered[
            filtered[target_col].astype(str).str.strip().ne(target_exclude)
        ]

    geocode_fail = filtered[
        is_blank(filtered["lat"]) | is_blank(filtered["lng"])
    ].copy()

    village_fail = filtered[
        ~is_blank(filtered["lat"])
        & ~is_blank(filtered["lng"])
        & is_blank(filtered[village_col])
    ].copy()

    def summarize(block):
        if block.empty:
            return pd.DataFrame()

        block = block.copy()
        block.insert(0, "row_index", block.index)
        block.insert(0, "_source_file", path.name)

        return block[["_source_file", "row_index", address_col]]

    return summarize(geocode_fail), summarize(village_fail)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Scan processed geospatial CSV files for unresolved records."
    )
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--addr-col", default="土地位置建物門牌")
    parser.add_argument("--target-col", default="交易標的")
    parser.add_argument("--target-exclude", default="土地")
    return parser.parse_args()


def main():
    args = parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    geocode_blocks = []
    village_blocks = []

    for path in input_dir.rglob("*.csv"):
        geocode_fail, village_fail = scan_file(
            path,
            address_col=args.addr_col,
            target_col=args.target_col,
            target_exclude=args.target_exclude,
        )

        if not geocode_fail.empty:
            geocode_blocks.append(geocode_fail)

        if not village_fail.empty:
            village_blocks.append(village_fail)

    if geocode_blocks:
        pd.concat(geocode_blocks, ignore_index=True).to_csv(
            output_dir / "ALL_geocode_fail.csv",
            index=False,
            encoding="utf-8-sig",
        )

    if village_blocks:
        pd.concat(village_blocks, ignore_index=True).to_csv(
            output_dir / "ALL_village_fail.csv",
            index=False,
            encoding="utf-8-sig",
        )

    print(
        f"[INFO] geocode failures: "
        f"{sum(len(x) for x in geocode_blocks)}"
    )
    print(
        f"[INFO] village failures: "
        f"{sum(len(x) for x in village_blocks)}"
    )


if __name__ == "__main__":
    main()

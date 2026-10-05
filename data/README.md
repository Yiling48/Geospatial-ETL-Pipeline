# Data

Raw research data are not included in this public repository.

The original workflow was used with:

1. **Taiwan real-estate transaction records**
   - address column: `土地位置建物門牌`
   - district column: `鄉鎮市區`
   - rows whose `交易標的` was `土地` could be skipped

2. **Point-of-interest / convenience-store data**
   - address column: `organizationaddress`

The public repository focuses on the reusable ETL logic rather than redistributing source datasets.

## Expected Output Fields

The pipeline adds:

- `lat`
- `lng`
- `nomi_address`
- `里`

You can place private input files under `data/raw/`; that directory is ignored by Git.

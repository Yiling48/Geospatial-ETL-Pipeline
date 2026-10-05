# Notebook Notes

The original development notebook was exploratory and contained:

- package installation cells
- machine-specific Windows file paths
- the full real-estate geocoding workflow
- a single-address geocoding test
- failure-report generation
- an adapted workflow for convenience-store addresses

For the public portfolio version, reusable logic has been refactored into:

- `src/geospatial_etl.py`
- `scripts/find_failures.py`

This keeps the repository portable and avoids committing local paths or research data.

If you want to preserve the original notebook for learning-history purposes, add a cleaned version here after:
1. removing machine-specific paths,
2. clearing outputs,
3. replacing private data references with examples.

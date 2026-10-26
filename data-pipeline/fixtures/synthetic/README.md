# SYNTHETIC TEST FIXTURES — NOT REAL DATA

Every file in this folder was invented for automated tests and the `demo` command.

- `synthetic_state_boundary.geojson`: an arbitrary polygon. It is **not** the Punjab boundary.
- `synthetic_districts.geojson`: two rectangles. They are **not** real districts.
- `synthetic_firms_viirs_window.csv`, `synthetic_firms_viirs_history.csv`: fabricated rows in
  FIRMS VIIRS layouts (NRT lower-case, and archive upper-case with `TYPE`). They are **not**
  satellite observations.
- `synthetic_cell_evidence.csv`: made-up `cropland_fraction` values, including some deliberate blanks.

All of them are marked as synthetic: the GeoJSON files with `"agni_scan_synthetic": true`, the CSV
files with `data_label=SYNTHETIC`. The pipeline therefore labels any output built from them as
`SYNTHETIC_DEMONSTRATION_NOT_REAL_SATELLITE_DATA` and gives the cell IDs a `SYNTH-` prefix.

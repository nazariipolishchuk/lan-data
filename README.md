# lan-data

Precomputed data for the Lan web app (NASA Space Apps Challenge 2026, "Field Shift").
Served by GitHub Pages at `/lan-data/`; the app's code is in the `lan` repository.

| Folder | Content | Sources |
|---|---|---|
| `tiles/` | Field outlines as PMTiles | Fields of The World (CC-BY-4.0) |
| `fields/` | Per-field area, soil, slope, crop history | NASA HLS, KPI/World Bank maps (CC-BY-4.0), SoilGrids (CC-BY-4.0), NASA NASADEM |
| `curves/` | Greenness curves per field and season | NASA HLS Vegetation Indices |
| `climate/` | Climate indicators per cell | NASA POWER |
| `meta.json` | Build date, coverage, measured accuracy, sources | — |
| `oblasts.json` | Oblast outlines with map layers summarised | geoBoundaries gbOpen (OpenStreetMap, ODbL 1.0) |
| `places.json.gz` | Settlement names for the search | GeoNames (CC-BY-4.0) |

Crop history is a satellite estimate, not a record. Licences of every source: `docs/REFERENCES.md` in `lan`.

# LandCoverExtraction Toolbox Documentation

## Overview
The **LandCoverExtraction** Python toolbox (`LandCoverExtraction.pyt`) provides two geoprocessing tools designed to:

1. Convert a folder of WaPOR (or similar classified) raster time-slices into cleaned, merged landcover polygons with dates.
2. Subdivide location polygons by intersecting them with the derived (time-enabled) landcover polygons in an optimized, batched workflow.

These tools help build a training/analysis-ready landcover change or temporal attribution dataset.

---
## Tools Summary
| Tool | Purpose | Key Outputs |
|------|---------|-------------|
| Raster to Polygon Landcover Extraction | Converts rasters to polygons, assigns class labels, removes small polygons, simplifies, merges, and writes a single polygon feature class with Date + Class fields. | Polygon FC with Date (DATE) and Class (TEXT) fields. |
| Spatial Join & Divide Locations by Landcover | Efficiently intersects a locations layer with large landcover polygons in batches, producing per-location landcover subdivisions with a sequential ID. | Polygon FC containing location attributes + landcover attributes + SeqID. |

---
## 1. Raster to Polygon Landcover Extraction
### Description
Processes all `.tif` rasters in an input folder. Each raster filename is expected to end with a pattern like: `YYYY-MM-D1`, `YYYY-MM-D2`, or `YYYY-MM-D3` (dekad indicator). A `.lyrx` file in the same folder supplies the mapping from `gridcode` to human-readable class names.

### Workflow Steps
1. Locate first `.lyrx` file in folder and parse colorizer groups → build `gridcode -> label` mapping.
2. Iterate all `.tif` rasters:
   - Sanitize name for use in `in_memory` workspace.
   - Convert raster to polygon (`Value` → `gridcode`).
   - Parse dekad date from filename → add `Date` field (DATE) and populate.
   - Remove polygons with area < 3600 m².
   - Simplify geometry (POINT_REMOVE, 60 m tolerance).
3. Merge all simplified polygon feature classes.
4. Repair geometry.
5. Add and populate `Class` field using mapping (fallback = "Unknown").
6. Write merged output feature class.

### Input Assumptions
- Each raster is thematic with integer class values.
- The `.lyrx` file uses `groups[].classes[].values[]` + `label` pattern.
- Filenames end with: `YYYY-MM-D[1-3]` (e.g., `2022-12-D3`).

### Output Schema (Key Fields)
| Field | Type | Notes |
|-------|------|-------|
| Date | DATE | Derived from filename dekad. |
| gridcode | SHORT/LONG | From raster to polygon conversion. |
| Class | TEXT | Human-readable landcover label. |

### Common Errors & Causes
| Error | Cause | Resolution |
|-------|-------|-----------|
| No .lyrx file found | Missing symbology file | Add correct `.lyrx` to folder. |
| Name pattern mismatch | Filename not ending in pattern | Rename or adjust regex if pattern changes. |
| ERROR 000354 | Invalid in-memory name | Handled via name sanitization; check unusual characters. |

---
## 2. Spatial Join & Divide Locations by Landcover
### Description
Intersects a large landcover polygon layer (often output of Tool 1 across multiple dates) with a locations polygon layer. Runs in batches to avoid memory/time explosion when processing millions of landcover features. Produces subdivision polygons retaining attributes from both sources and adds a sequential `SeqID` field.

### Key Optimizations
- Batching location features (default 500) to limit spatial selection scope.
- Spatial preselection of landcover subset (`SelectLayerByLocation`) per batch before intersect.
- PairwiseIntersect on reduced subsets.
- Streaming Copy/Append writes to the output incrementally.
- Optional retention of intermediate subsets for debugging.

### Parameters
| Parameter | Name | Type | Required | Notes |
|-----------|------|------|----------|-------|
| Locations Feature Layer | locations_fc | GPFeatureLayer | Yes | Polygon layer with identifier field. |
| Time-enabled Landcover Polygon Layer | landcover_fc | GPFeatureLayer | Yes | Large merged landcover polygons. |
| Location ID Field | location_id_field | Field | Yes | Must exist in locations layer. |
| Output Feature Class | output_fc | DEFeatureClass | Yes | Target output. |
| Batch Size (locations per chunk) | batch_size | Long | No (default 500) | Tune for performance. |
| Keep Intermediates (Debug) | keep_intermediates | Boolean | No | If True, leaves in_memory subsets. |

### Output Fields (Partial)
| Field | Source | Description |
|-------|--------|-------------|
| location_id_field | Locations | Original location identifier. |
| SeqID | Tool | Sequential unique ID across all intersection fragments. |
| gridcode / Class / Date | Landcover | Passed through if present from Tool 1 output. |

### Performance Tuning Guidance
| Scenario | Suggested Adjustment |
|----------|----------------------|
| Very sparse overlap | Reduce batch size (e.g., 250) to minimize wasted selection. |
| Dense overlap / small geometries | Increase batch size (750–1000) if memory allows. |
| Memory pressure | Ensure `keep_intermediates` is False. |
| Slow selection | Add spatial index to landcover dataset (in a file GDB). |

### Internal Logic Pseudocode
```
for each batch of location OIDs:
  build where clause (chunked IN lists)
  remake filtered location layer
  select intersecting landcover polygons
  copy subset → in_memory
  if empty: continue
  pairwise intersect subset with batch locations
  add SeqID values (global counter)
  append to output
cleanup unless debug flag
```

### Limitations / Notes
- No explicit date filtering; all landcover features are treated uniformly.
- Attribute name conflicts resolved by ArcGIS suffixing (e.g., field_1).
- `SeqID` changes if batch size changes (for stable IDs derive from attributes). 
- Not parallelized (ArcGIS Python toolbox constraint).

### Extending the Tool
| Enhancement | Benefit |
|-------------|---------|
| Date filter parameter | Limit to time window. |
| Dominant class summarizer | Reduce data volume per location. |
| Area % fields | Enable weighted analytics. |
| Dissolve per (LocationID, Date, Class) | Produce non-overlapping summaries. |
| Parallel external script | Faster on multi-core machines. |

---
## Example Usage (ArcGIS Pro)
1. Add toolbox (`LandCoverExtraction.pyt`) to a project.
2. Run Tool 1 (Raster to Polygon Landcover Extraction):
   - Input Folder: `D:/data/wapor_2022/`
   - Output Feature Class: `D:/gdb/wapor.gdb/wapor_poly_2022`
3. Run Tool 2 (Spatial Join & Divide Locations by Landcover):
   - Locations Feature Layer: `plots_layer`
   - Time-enabled Landcover Polygon Layer: `wapor_poly_2020_2024`
   - Location ID Field: `PlotID`
   - Output Feature Class: `D:/gdb/analysis.gdb/plots_landcover_subdiv`
   - (Optional) Batch Size: `750`

---
## Troubleshooting
| Symptom | Possible Cause | Resolution |
|---------|----------------|-----------|
| Tool 2 long runtime | Batch too large or no spatial index | Lower batch size; add spatial index to landcover. |
| Empty output | No spatial overlap | Validate coordinate systems & extents. |
| Missing Class field | .lyrx mapping mismatch | Inspect .lyrx JSON structure. |
| Memory errors | Too many intermediates retained | Ensure `keep_intermediates=False`. |

---
## Best Practices
- Store outputs in a file geodatabase (not shapefiles) for speed and field name preservation.
- Pre-create spatial indexes on large landcover datasets.
- Run heavy jobs on SSD storage.
- Avoid huge batch sizes (>1500) unless overlap density is very high and RAM is ample.
- Consider archiving the raw raster chips; polygon extraction is deterministic if inputs unchanged.

---
## Versioning & Change Log (Manual)
| Date | Change |
|------|--------|
| 2025-09-17 | Initial public documentation added. |

---
## License
Refer to root repository LICENSE for usage terms.

---
## Feedback / Improvements
Open an issue or submit a pull request describing desired enhancements (e.g., temporal aggregation, dominant class summarization, or mosaic dataset integration).

# Automated Feature Extraction and Classification

`AutomatedFeatureExtraction.pyt` is an ArcGIS Pro Python toolbox for general image-based feature extraction and similarity classification. Its ArcPy toolbox alias is `automatedfeatureextraction`.

## Workflows

1. **Feature Extraction** uses Living Atlas SAM3 to create polygon evidence for a controlled topographic profile. Persistent candidate profiles include Buildings, Bridges, Roads, Water Bodies, Rail Corridors, Impervious Surfaces, Parking Areas, Solar Arrays, Sports Surfaces, Swimming Pools, Trees, Forest Cover, and Other Structures. Roads receive dedicated surface QA to repair masks, bridge sub-meter occlusion gaps, fill small enclosed holes, and smooth pixel stair-steps. Agricultural Fields, Park-Like Green Space, Construction Areas, Material Stockpiles, Bare Ground, Flooded Areas, Debris, Vehicles, and Utility Poles are observation or change-monitoring profiles, not stable base-map features. Park-Like Green Space represents visible vegetation and amenities; it cannot establish a legal park or land-use designation. `Custom` remains evidence-only until its feature code, geometry, and QA rules have been governed.
2. **Embedding Similarity** generates embeddings for analysis imagery and returns cells that resemble at least six representative example points. This is useful when the output is a single visual concept and no class label is needed.
3. **Feature Classification** classifies target polygons using an independent similarity search for every populated value in an example-point class field. Supply **Input Features to Classify** to classify existing polygons, or leave it blank to extract target features with SAM3 before classification. The output is the target feature layer with `AUTO_CLASS` and `CLASS_COV_PCT`, the percentage covered by the strongest matching class evidence.

For example, create a point feature class with a `roof_type` field and assign values such as `Green Roof` and `Brick Roof`. Supply that layer and choose `roof_type` as **Example Class Field**. Each class needs at least six points, and each class must intersect at least six unique embedding cells.

The derived similar-features output keeps class-specific evidence in `AFE_CLASS`. The final target output assigns the class with the greatest overlapping evidence; targets without matching evidence are marked `Unclassified`. Equal strongest evidence is marked `Ambiguous`, never resolved by processing order. `CLASS_REASON` and `EVIDENCE_METRIC` explain the outcome.

## Inputs

Feature Extraction uses an active-map raster layer or a World Imagery Wayback release. Similarity workflows use an active-map raster layer, Current World Imagery, a Wayback release, or existing embeddings with a BLOB embedding field. Provide an AOI polygon or set the Processing Extent environment for imagery processing.

The tool downloads and caches Living Atlas SAM3 and the selected embedding model when a local `.dlpk` is not supplied. It supports EO-DINO, DINOv2, and DINOv3 embedding packages. Retained embeddings created by the current toolbox are automatically discovered and reused across feature types when their signed source imagery, model, grid size, coordinate system, and coverage match the requested analysis. Older or unsigned embeddings can still be selected manually through **Existing Embeddings**.

## Code Structure

`AutomatedFeatureExtraction.pyt` remains the ArcGIS Pro toolbox entry point and workflow coordinator. Shared ArcPy parameter construction lives in `parameter_helpers.py`; field, workspace, unit, and coverage validation lives in `validation_helpers.py`. New reusable toolbox behavior should be added to a focused Python module rather than expanding the entry point.

## Outputs

**Output Features** is the main result: candidate polygons for Feature Extraction, matching embedding cells for Embedding Similarity, or classified target polygons for Feature Classification. It is an auditable candidate layer, never an automatically accepted authoritative topographic update. Every output records `AFE_RUN_ID`, `FEATURE_CODE`, `FEATURE_TYPE`, `GEOM_ROLE`, `QC_STATUS`, `QC_REASON`, `TOOL_VERSION`, `PROFILE_VER`, `SOURCE_IMAGE`, `MODEL_ITEM_ID`, `MODEL_FILE`, `RUN_UTC`, and `AREA_SQM`.

Candidates smaller than the profile minimum area are retained as `Rejected`; all other automated outputs are `NeedsReview`. This makes filtering and manual acceptance explicit rather than silently dropping uncertain evidence. Output publication is staged so an existing output remains intact if candidate processing fails before publication. The derived Embeddings and Similar Features outputs can be retained for inspection or reruns. Store output feature classes in a file or enterprise geodatabase because embeddings contain BLOB fields.

## Requirements

- ArcGIS Pro with the GeoAI, Image Analyst, and 3D Analyst tools
- ArcGIS deep-learning libraries and a supported GPU
- Internet access for Wayback imagery and first-time model downloads
- A projected AOI or Processing Extent when imagery needs to be processed

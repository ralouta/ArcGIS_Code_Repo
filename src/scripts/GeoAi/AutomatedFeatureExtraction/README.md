# Automated Feature Extraction and Classification

`AutomatedFeatureExtraction.pyt` is an ArcGIS Pro Python toolbox for general image-based feature extraction and similarity classification. Its ArcPy toolbox alias is `automatedfeatureextraction`.

## Workflows

1. **Feature Extraction** uses Living Atlas SAM3 to create polygons for a selected feature type. Use a built-in type such as Buildings, Roads, Debris, Vehicles, Trees, or Utility Poles, or select `Custom` and provide a SAM3 text prompt.
2. **Embedding Similarity** generates embeddings for analysis imagery and returns cells that resemble at least six representative example points. This is useful when the output is a single visual concept and no class label is needed.
3. **Feature Classification** classifies target polygons using an independent similarity search for every populated value in an example-point class field. Supply **Input Features to Classify** to classify existing polygons, or leave it blank to extract target features with SAM3 before classification. The output is the target feature layer with `AUTO_CLASS` and `CLASS_COV_PCT`, the percentage covered by the strongest matching class evidence.

For example, create a point feature class with a `roof_type` field and assign values such as `Green Roof` and `Brick Roof`. Supply that layer and choose `roof_type` as **Example Class Field**. Each class needs at least six points, and each class must intersect at least six unique embedding cells.

The derived similar-features output keeps class-specific evidence in `AFE_CLASS`. The final target output assigns the class with the greatest overlapping evidence; targets without matching evidence are marked `Unclassified`.

## Inputs

Feature Extraction uses an active-map raster layer or a World Imagery Wayback release. Similarity workflows use an active-map raster layer, Current World Imagery, a Wayback release, or existing embeddings with a BLOB embedding field. Provide an AOI polygon or set the Processing Extent environment for imagery processing.

The tool downloads and caches Living Atlas SAM3 and the selected embedding model when a local `.dlpk` is not supplied. It supports EO-DINO, DINOv2, and DINOv3 embedding packages.

## Outputs

**Output Features** is the main result: extracted polygons for Feature Extraction, matching embedding cells for Embedding Similarity, or classified target polygons for Feature Classification. The derived Embeddings and Similar Features outputs can be retained for inspection or reruns. Store output feature classes in a file or enterprise geodatabase because embeddings contain BLOB fields.

## Requirements

- ArcGIS Pro with the GeoAI, Image Analyst, and 3D Analyst tools
- ArcGIS deep-learning libraries and a supported GPU
- Internet access for Wayback imagery and first-time model downloads
- A projected AOI or Processing Extent when imagery needs to be processed

# Damage Assessment

`DamageAssessment.pyt` contains two ArcGIS Pro tools:

- **Automated Damage Assessment** runs target extraction, post-event embedding generation, similarity search, and overlap classification.
- **Classify Building Damage from Similar Embeddings** preserves the standalone classifier from `BuildingDamageAssessment` for reruns with existing inputs.

## Automated workflow

1. Use supplied target polygons, or extract targets from pre-event imagery with SAM3.
2. Run nonmaximum suppression on SAM3 results and regularize building footprints.
3. Intersect damage example points with the target polygons. The points must identify 6-20 unique targets.
4. Generate EO-DINO embeddings from post-event imagery only.
5. Find embeddings similar to the selected damaged targets.
6. Classify every target by the percentage covered by similar embedding polygons.

When local model paths are empty, the tool downloads and caches these public packages:

- SAM3: ArcGIS item `37ef2e1ba0c042ce99501f56295ec0d4`
- EO-DINO: ArcGIS item `93e8b9ad20734fe7a1641e46385535fc`

These are the default extraction and embedding models. To use another compatible model, provide its local `.dlpk` in the corresponding **Custom Model** parameter; the supplied package overrides the default for that run.

## Requirements

- ArcGIS Pro with the GeoAI, Image Analyst, and 3D Analyst tools used by the workflow
- ArcGIS deep learning libraries and a supported GPU
- Internet access for World Imagery Wayback and first-time model downloads
- Target features and area of interest in a projected coordinate system
- Classified output stored in a file or enterprise geodatabase

The Wayback dropdown is populated from Esri's current Wayback catalog. If ArcGIS Pro cannot add the selected WMTS item automatically, add that dated World Imagery Wayback layer to the active map and rerun the tool.

Feature-specific cell sizes are starting profiles and remain editable. Set **Embedding Grid Size** to `0` to estimate an odd grid size from the median target width, or provide a tested value such as `5`.

Damage classes are relative image evidence, not confirmation of structural damage. Validate moderate and high results against post-event imagery or field observations.
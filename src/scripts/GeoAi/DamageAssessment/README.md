# Damage Assessment

`DamageAssessment.pyt` contains the **Automated Damage Assessment** ArcGIS Pro tool. It runs target extraction, post-event embedding generation, similarity search, and overlap classification.

When imported with ArcPy, the toolbox alias is `automateddamageassessment`.

The standalone **Classify Building Damage from Similar Embeddings** tool remains under `QAQC/BuildingDamageAssessment` for reruns with existing inputs.

## Automated workflow

1. Use supplied target polygons, or extract targets from pre-event imagery with SAM3.
2. Run nonmaximum suppression on SAM3 results and regularize building footprints with area-scaled tolerances, including finer tolerances for small buildings.
3. Build query regions from at least 6 damage example points. For roads, points intersecting or within 10 meters of an inferred road pass a proximity QA check and create local 10-meter-radius query regions; farther points are ignored and reported. Other feature types require the points to identify at least 6 unique targets.
4. Generate embeddings from post-event imagery using the selected ArcGIS Online model.
5. Find embeddings similar to the selected damaged targets.
6. Classify every target by the percentage covered by similar embedding polygons.

When local model paths are empty, the tool downloads and caches these public packages automatically in the current user's ArcGIS Packages folder. There is no cache parameter to configure.

- SAM3: ArcGIS item `37ef2e1ba0c042ce99501f56295ec0d4`
- EO-DINO (default, multisensor/RGB): ArcGIS item `93e8b9ad20734fe7a1641e46385535fc`
- DINOv2 (RGB): ArcGIS item `17cae00c93194903a4bcb7853ab51b21`
- DINOv3 (RGB): ArcGIS item `fbb8448003dc43aa8b69b46776606dd6`

Choose an embedding package from the **ArcGIS Online Embedding Model** dropdown. The selected package is downloaded and cached automatically. To use another compatible model, provide its local `.dlpk` in the corresponding **Custom Model** parameter; the supplied package overrides the online selection for that run.

## Requirements

- ArcGIS Pro with the GeoAI, Image Analyst, and 3D Analyst tools used by the workflow
- ArcGIS deep learning libraries and a supported GPU
- Internet access for World Imagery Wayback and first-time model downloads
- Target features and area of interest in a projected coordinate system
- Classified output stored in a file or enterprise geodatabase

Input imagery with another defined coordinate system is opened from its underlying raster or mosaic dataset, wrapped in the virtual **Reproject** raster function, and processed as WGS 1984 Web Mercator (Auxiliary Sphere). The source raster is not rewritten.

The pre-event and post-event imagery dropdowns list raster layers from the active map. The Wayback dropdown is populated from Esri's current archive catalog. Wayback release dates are global archive publication dates, not local image acquisition dates; each release is a global basemap, so AOI overlap does not meaningfully reduce the list. If ArcGIS Pro cannot add the selected WMTS item automatically, add that dated World Imagery Wayback layer to the active map and rerun the tool.

For feature extraction, either provide an **Area of Interest Polygon** or open the tool's **Environments** settings and set **Extent** to Current Display Extent, a map layer, or specified coordinates. An AOI polygon takes precedence when both are supplied. With existing target features and neither option set, their full extent is used.

Feature-specific detection cell sizes are starting profiles and remain editable. Leave **Embedding Grid Size** blank to automatically estimate an odd grid size from the median target width and post-event image resolution, or provide a tested positive value such as `5`.

Built-in extraction profiles are available for buildings, bridges, roads, debris, vehicles, trees, and utility poles. Choose **Custom** to supply another SAM3 text prompt.

The tool validates the minimum of 6 damage-example features in the ArcGIS Pro dialog before execution. Road proximity to inferred features is checked later, after SAM3 extraction.

Damage classes are relative image evidence, not confirmation of structural damage. Validate moderate and high results against post-event imagery or field observations.

Leave **Keep Intermediate Data** checked to retain generated target features, post-event embeddings, and similar embedding features. Uncheck it to delete those generated datasets after the classified output is created. User-supplied target features are never deleted.
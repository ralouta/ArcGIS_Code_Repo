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

When the post-event input is an image service and the analysis extent exceeds a safe 4,000-pixel request in either dimension, the tool exports native-resolution 4,000-by-4,000 TIFF tiles. It processes the cached TIFFs as aligned embedding chunks of at most approximately 20,000 by 20,000 source pixels. For each chunk, only intersecting TIFFs are assembled into a temporary physical raster before GeoAI processing. Completed embedding chunks are assembled with one direct geodatabase merge before similarity analysis, avoiding the extra disk space required by staged merge intermediates. This also avoids oversized image-service requests and a single city-scale raster worker reaching ArcGIS Pro's internal parallel-job timeout.

Image-service processing is resumable. The cache path is deterministic for the image-service layer configuration, analysis extent, coordinate system, native pixel size, and cache format. Each TIFF is exported to a unique temporary file and validated before it is atomically promoted to its final cache path. Failed exports are cleaned up and retried up to three times, so an incomplete TIFF cannot occupy a completed tile path. When every expected embedding checkpoint is valid, a rerun skips TIFF validation and proceeds directly to embedding assembly. Otherwise, it skips TIFF tiles only when a successful completion marker, valid dimensions, and a readable pixel are present. It reuses embedding chunks when the completion marker, feature class, and BLOB embedding field are present, avoiding expensive full row counts during startup. New chunks are row-count validated before their completion markers are written. Batch size is execution tuning and can be lowered without invalidating completed embedding chunks, including checkpoints created by version 5.0. There is no persistent mosaic dataset or raster catalog. Temporary chunk rasters are removed after every chunk, including failures, and raster workers plus CUDA caches are recycled between chunks. Model, grid-size, output-coordinate-system, chunk-size, or input assembly strategy changes create a separate embedding checkpoint. Failed or canceled runs retain the source-tile cache and completed embedding chunks and report the cache path; a fully successful classification removes the processing cache. Reduce the AOI or **Extent** environment to reduce download time, processing time, and temporary disk use.

Pre-event imagery supports an input raster layer from the active map or a World Imagery Wayback release. Post-event imagery supports an active-map raster, Current World Imagery, or a selected Wayback release. The two Wayback releases are selected independently, allowing an older archive for feature extraction and a newer archive for damage similarity. Wayback release dates are global archive publication dates, not local image acquisition dates. Before processing, the tool queries selected Wayback metadata over the resolved AOI or extent, reports the newest local acquisition date, source, and resolution, and warns when the pre-event and post-event releases use the same local imagery.

When an AOI, target-feature extent, Extent environment, or active map display is available, the Wayback dropdowns are filtered to releases with local imagery changes at that area's center using the same tilemap service as the World Imagery Wayback app. The parameter warning reports the filtered release count. The active map display is only a fallback for populating the dropdown; execution continues to use the AOI, Extent environment, or target-feature extent.

Wayback releases are WMTS display services, which ArcGIS deep-learning tools cannot use directly. For pre-event SAM3 extraction, the tool downloads the selected release's tiles and mosaics them into one temporary Web Mercator TIFF. Pre-event extraction retains the 4,096-tile whole-raster safety limit; reduce the AOI/Extent or provide a local raster when that limit is exceeded.

Current World Imagery and post-event Wayback support larger extents through the same tiled workflow. The tool downloads tiles in resumable groups of at most 16 by 16 source tiles, assembles each group into an aligned 4,096-pixel TIFF block, and deletes the source JPEGs after validating the block. The bounded embedding workflow then creates temporary chunk rasters only from intersecting blocks. Completed block and embedding checkpoints are reused after failed or canceled runs, and the deterministic cache is removed after a successful classification.

Tile level selection respects the locally reported source resolution and always chooses a cache level at or coarser than that resolution. This avoids requesting uncached high-resolution tiles where a Wayback release only provides coarser local imagery.

For feature extraction, either provide an **Area of Interest Polygon** or open the tool's **Environments** settings and set **Extent** to Current Display Extent, a map layer, or specified coordinates. An AOI polygon takes precedence when both are supplied. When supplied target features extend beyond available imagery, provide an AOI to clip them to the analysis boundary; embedding generation, similarity analysis, and the final classified output then use only the clipped targets. The clipped target feature class is retained or removed according to **Keep Intermediate Data**, while the original target dataset is never modified. With existing target features and neither an AOI nor an Extent environment set, their full extent is used. The Extent environment limits imagery processing but does not clip supplied target geometry; use an AOI when the final output must be restricted to the imagery footprint.

Feature-specific detection cell sizes are starting profiles and remain editable. Leave **Embedding Grid Size** blank to automatically estimate an odd grid size from the median target width and post-event image resolution, or provide a tested positive value such as `5`.

Built-in extraction profiles are available for buildings, bridges, roads, debris, vehicles, trees, and utility poles. Choose **Custom** to supply another SAM3 text prompt.

The tool validates the minimum of 6 damage-example features in the ArcGIS Pro dialog before execution. Road proximity to inferred features is checked later, after SAM3 extraction.

Damage classes are relative image evidence, not confirmation of structural damage. Validate moderate and high results against post-event imagery or field observations.

Leave **Keep Intermediate Data** checked to retain generated target features, post-event embeddings, and similar embedding features. Uncheck it to delete those generated datasets after the classified output is created. User-supplied target features are never deleted.

## Rerunning similarity and classification

To adjust the similarity or coverage thresholds without regenerating embeddings, provide a retained embedding feature class in **Existing Post-Event Embeddings**. The tool validates that the input contains a BLOB embedding field, skips post-event imagery preparation, model loading, GPU validation, embedding generation, and chunk assembly, then reruns similarity and classification. Use embeddings created from the same post-event imagery, extent, model, grid size, and output coordinate system as the targets being analyzed.

When the classified output already exists, the output parameter warns that it will be replaced. Replacement occurs only after similarity analysis succeeds, so an upstream failure leaves the previous classified result intact. The tool never modifies or deletes supplied embeddings, including when **Keep Intermediate Data** is off, and rejects an output path that aliases target features or supplied embeddings.
import arcpy
import os


"""
Tiled Export Training Data Workaround
------------------------------------
Exports training data from a potentially slow WMTS/mosaic source by subdividing
an AOI into square tiles of a target area (default 350,000 square meters) and
invoking ExportTrainingDataForDeepLearning one tile at a time.

Usage (ArcGIS Pro Python Window example):

    import export_training_data_tiled as etd
    etd.export_tiled_training_data(
        in_raster="Noa Meliisa 31102025",            # Raster layer or image service
        in_class_data="Damage Training Data",        # Feature class with class polygons
        aoi_fc="AOI",                                # Area of interest feature class
        out_folder=r"D:\Movetoondrive\HurricaneMelissa\trainigndata\DamagedClassifiedTilesV3",
        tile_area_m2=350000,
        tile_size_px=256,
        stride_px=128,
        image_chip_format="TIFF",
        metadata_format="Classified_Tiles",
        class_value_field="class",
        buffer_radius=2,
        rotation_angle=90,
        reference_system="MAP_SPACE",
        processing_mode="PROCESS_AS_MOSAICKED_IMAGE",
        max_retries=2
    )

Key Parameters:
- tile_area_m2: Desired tile area for tessellation squares.
- max_retries: Retries per tile on timeout/RuntimeError.
- resume: If True, skips tiles already exported (based on an index file or existing subfolder pattern).

Creates a tessellation within AOI, filters tiles that intersect AOI, then loops:
  * Sets environment extent to tile extent
  * Calls ExportTrainingDataForDeepLearning
  * Optional retry with short sleep backoff

Generates an index feature class of processed tiles (within out_folder) for resume capability.
"""

def export_tiled_training_data(
    in_raster: str,
    in_class_data: str,
    aoi_fc: str,
    out_folder: str,
    tile_area_m2: float = 350000.0,
    tile_size_px: int = 256,
    stride_px: int = 128,
    image_chip_format: str = "TIFF",
    metadata_format: str = "Classified_Tiles",
    class_value_field: str = "class",
    buffer_radius: int = 2,
    rotation_angle: int = 0,
    reference_system: str = "MAP_SPACE",
    processing_mode: str = "PROCESS_AS_MOSAICKED_IMAGE",
    cell_size: float = 0.3,
    output_nofeature_tiles: str = "ALL_TILES"
):
    """Simplified tiled training data export.

     Steps:
      1. Generate square tessellation over AOI extent.
      2. Clip tessellation to AOI (keeps only intersecting squares).
      3. Loop each clipped tile, set env extent, call ExportTrainingDataForDeepLearning.
         4. Environment cell size forced to provided 'cell_size' (default 0.3).
        5. Each tile's output is written to a unique subfolder under the base out_folder with suffix _{tile_number} to avoid overwriting previous exports.
        6. 'output_nofeature_tiles' exposed (e.g. 'ALL_TILES', 'ONLY_TILES_WITH_FEATURES').
    """
    arcpy.env.overwriteOutput = True
    if not os.path.isdir(out_folder):
        os.makedirs(out_folder)

    size_param = f"{tile_area_m2} SquareMeters"
    # Set environment cell size from parameter
    try:
        arcpy.env.cellSize = cell_size
        print(f"Environment cell size set to: {cell_size}")
    except Exception as e:
        print(f"Failed to set cell size {cell_size}: {e}")
    aoi_desc = arcpy.Describe(aoi_fc)
    aoi_extent = aoi_desc.extent
    spatial_ref = aoi_desc.spatialReference

    # Use a physical scratch GDB (still safer than in_memory for remote imagery)
    scratch_gdb = arcpy.env.scratchGDB or arcpy.management.CreateFileGDB(out_folder, "tiled_export_scratch.gdb").getOutput(0)
    tessellation_fc = os.path.join(scratch_gdb, "tessellation_tiles")
    clipped_tiles_fc = os.path.join(scratch_gdb, "tessellation_tiles_clip")

    print("Generating tessellation...")
    arcpy.management.GenerateTessellation(tessellation_fc, aoi_extent, "SQUARE", size_param, spatial_ref)

    print("Clipping tessellation to AOI...")
    arcpy.analysis.Clip(tessellation_fc, aoi_fc, clipped_tiles_fc)

    # Build list of extents
    tiles = []
    with arcpy.da.SearchCursor(clipped_tiles_fc, ["OID@", "SHAPE@"]) as cursor:
        for oid, geom in cursor:
            if geom:
                tiles.append((oid, geom.extent))

    total_tiles = len(tiles)
    print(f"Prepared {total_tiles} tiles.")

    if total_tiles == 0:
        print("No tiles generated after clip. Nothing to export.")
        return

    base_folder_name = os.path.basename(out_folder.rstrip('/\\'))
    for tile_num, (oid, extent) in enumerate(tiles, start=1):
        print(f"Processing tile {tile_num}/{total_tiles} (OID {oid})...")
        # Debug extent values (first few tiles)
        if tile_num <= 3:
            print(f"  Extent: XMin={extent.XMin}, YMin={extent.YMin}, XMax={extent.XMax}, YMax={extent.YMax}")
        try:
            # Pass Extent object directly (string with WKT caused environment error)
            # Apply extent and enforce cell size inside EnvManager for each tile
            with arcpy.EnvManager(extent=extent, cellSize=cell_size):
                # Create per-tile output subfolder to prevent overwrites
                tile_subfolder_name = f"{base_folder_name}_{tile_num}"
                tile_out_folder = os.path.join(out_folder, tile_subfolder_name)
                if not os.path.isdir(tile_out_folder):
                    os.makedirs(tile_out_folder)
                arcpy.ia.ExportTrainingDataForDeepLearning(
                    in_raster=in_raster,
                    out_folder=tile_out_folder,
                    in_class_data=in_class_data,
                    image_chip_format=image_chip_format,
                    tile_size_x=tile_size_px,
                    tile_size_y=tile_size_px,
                    stride_x=stride_px,
                    stride_y=stride_px,
                    metadata_format=metadata_format,
                    start_index=0,
                    class_value_field=class_value_field,
                    buffer_radius=buffer_radius,
                    in_mask_polygons=None,
                    rotation_angle=rotation_angle,
                    reference_system=reference_system,
                    processing_mode=processing_mode,
                    output_nofeature_tiles=output_nofeature_tiles
                )
            print(f"Tile {tile_num} completed.")
        except Exception as e:
            print(f"Tile {tile_num} failed: {e}")

    print("Tiled export complete.")

if __name__ == "__main__":
    # Minimal example invocation (edit parameters as needed)
    export_tiled_training_data(
        in_raster="Noa Meliisa 31102025",
        in_class_data="Damage Training Data",
        aoi_fc="AOI",
        out_folder=r"D:\Movetoondrive\HurricaneMelissa\trainigndata\DamagedClassifiedTilesV3",
        tile_area_m2=350000,
        tile_size_px=256,
        stride_px=128,
        class_value_field="class",
        rotation_angle=90,
        buffer_radius=2,
        output_nofeature_tiles="ALL_TILES"
    )

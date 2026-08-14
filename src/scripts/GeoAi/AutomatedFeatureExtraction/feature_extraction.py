import re

import arcpy


def extract_target_features(
    source_imagery, analysis_extent, spatial_reference, feature_type, prompt, sam_model,
    cell_size, batch_size, gpu_id, output_workspace, output_features, scratch_workspace,
    messages, *, output_name_prefix, meters_to_spatial_units, prepare_extraction_raster,
    feature_profile, duplicate_iou_threshold, envelope_min_children,
    envelope_min_coverage, envelope_max_coverage, regularize_building_footprints,
    clean_road_surfaces, clean_agricultural_fields,
):
    raw_features = arcpy.CreateUniqueName("sam3_raw", scratch_workspace)
    nms_features = arcpy.CreateUniqueName("sam3_nms", scratch_workspace)
    qa_features = arcpy.CreateUniqueName("sam3_qa_candidates", scratch_workspace)
    safe_feature_type = re.sub("[^A-Za-z0-9_]+", "_", feature_type)
    target_features = arcpy.CreateUniqueName(
        f"{output_name_prefix(output_features)}_{safe_feature_type}", output_workspace
    )
    cell_size_units = meters_to_spatial_units(cell_size, spatial_reference)

    try:
        messages.addMessage(f"Detecting {feature_type.lower()} with SAM3...")
        extraction_raster = prepare_extraction_raster(source_imagery, messages)
        with arcpy.EnvManager(
            gpuId=gpu_id,
            extent=analysis_extent,
            cellSize=cell_size_units,
            processorType="GPU",
            outputCoordinateSystem=spatial_reference,
        ):
            arcpy.ia.DetectObjectsUsingDeepLearning(
                in_raster=extraction_raster,
                out_detected_objects=raw_features,
                in_model_definition=sam_model,
                arguments=(
                    f"text_prompt {prompt};padding 128;batch_size {batch_size};"
                    "box_nms_thresh 0.5;points_per_batch 64;"
                    "stability_score_thresh 0.35;min_mask_region_area 0"
                ),
                run_nms="NO_NMS",
                confidence_score_field="Confidence",
                class_value_field="Class",
                max_overlap_ratio=0,
                processing_mode="PROCESS_AS_MOSAICKED_IMAGE",
                use_pixelspace="NO_PIXELSPACE",
                in_objects_of_interest=None,
            )
        raw_detection_count = int(arcpy.management.GetCount(raw_features)[0])
        messages.addMessage(f"Raw SAM3 detections: {raw_detection_count}")
        messages.addMessage(
            f"Removing only near-identical masks at {duplicate_iou_threshold:.0%} IoU; "
            "all other overlapping candidates are retained."
        )
        remove_near_duplicate_polygons(
            raw_features, nms_features, duplicate_iou_threshold, scratch_workspace
        )
        detection_count = int(arcpy.management.GetCount(nms_features)[0])
        messages.addMessage(f"SAM3 detections after near-duplicate removal: {detection_count}")
        rejected_envelope_count = remove_overgrown_polygon_masks(
            nms_features, qa_features, scratch_workspace, envelope_min_children,
            envelope_min_coverage, envelope_max_coverage,
        )
        if rejected_envelope_count:
            messages.addMessage(
                f"Rejected {rejected_envelope_count:,} broad polygon mask(s) that enclosed "
                "multiple distinct smaller detections."
            )

        if feature_profile["regularize"]:
            regularize_building_footprints(
                qa_features, target_features, spatial_reference, scratch_workspace, messages
            )
        elif feature_type == "Roads":
            clean_road_surfaces(
                qa_features, target_features, feature_profile, spatial_reference,
                scratch_workspace, messages,
            )
        elif feature_type == "Agricultural Fields":
            clean_agricultural_fields(
                qa_features, target_features, feature_profile, spatial_reference,
                scratch_workspace, messages,
            )
        else:
            arcpy.management.CopyFeatures(qa_features, target_features)
    finally:
        for dataset in (raw_features, nms_features, qa_features):
            if arcpy.Exists(dataset):
                arcpy.management.Delete(dataset)

    if int(arcpy.management.GetCount(target_features)[0]) == 0:
        raise arcpy.ExecuteError(
            f"SAM3 did not extract any {feature_type.lower()} in the area of interest."
        )
    return target_features


def remove_near_duplicate_polygons(input_features, output_features, iou_threshold, scratch_workspace):
    ranked_features = []
    with arcpy.da.SearchCursor(input_features, ["OID@", "SHAPE@", "Confidence"]) as cursor:
        for object_id, geometry, confidence in cursor:
            if geometry and geometry.getArea("GEODESIC", "SQUAREMETERS") > 0:
                ranked_features.append((object_id, geometry, float(confidence or 0)))
    ranked_features.sort(key=lambda feature: (-feature[2], feature[0]))

    retained_geometries = []
    retained_ids = []
    for object_id, geometry, _ in ranked_features:
        geometry_area = geometry.getArea("GEODESIC", "SQUAREMETERS")
        is_duplicate = False
        for retained_geometry, retained_area in retained_geometries:
            if geometry.disjoint(retained_geometry):
                continue
            intersection = geometry.intersect(retained_geometry, 4)
            intersection_area = intersection.getArea("GEODESIC", "SQUAREMETERS")
            union_area = geometry_area + retained_area - intersection_area
            if union_area and intersection_area / union_area >= iou_threshold:
                is_duplicate = True
                break
        if not is_duplicate:
            retained_ids.append(object_id)
            retained_geometries.append((geometry, geometry_area))

    if not retained_ids:
        raise arcpy.ExecuteError("No valid polygon detections were available for duplicate removal.")
    keep_field = "AFE_KEEP_MASK"
    selected_features = arcpy.CreateUniqueName("deduplicated_polygons", scratch_workspace)
    try:
        arcpy.management.AddField(input_features, keep_field, "SHORT")
        retained_id_set = set(retained_ids)
        with arcpy.da.UpdateCursor(input_features, ["OID@", keep_field]) as cursor:
            for object_id, _ in cursor:
                cursor.updateRow([object_id, int(object_id in retained_id_set)])
        field_delimiter = arcpy.AddFieldDelimiters(input_features, keep_field)
        arcpy.management.MakeFeatureLayer(input_features, selected_features, f"{field_delimiter} = 1")
        arcpy.management.CopyFeatures(selected_features, output_features)
        arcpy.management.DeleteField(output_features, keep_field)
    finally:
        if arcpy.Exists(selected_features):
            arcpy.management.Delete(selected_features)


def remove_overgrown_polygon_masks(
    input_features, output_features, scratch_workspace, minimum_children,
    minimum_coverage, maximum_coverage,
):
    candidates = []
    with arcpy.da.SearchCursor(input_features, ["OID@", "SHAPE@", "Confidence"]) as cursor:
        for object_id, geometry, confidence in cursor:
            area = geometry.getArea("GEODESIC", "SQUAREMETERS") if geometry else 0.0
            if area > 0:
                candidates.append((object_id, geometry, area, float(confidence or 0)))

    rejected_ids = set()
    for object_id, geometry, area, _ in candidates:
        contained_masks = []
        for other_id, other_geometry, other_area, _ in candidates:
            if other_id == object_id or other_area >= area * 0.5 or geometry.disjoint(other_geometry):
                continue
            intersection = geometry.intersect(other_geometry, 4)
            intersection_area = intersection.getArea("GEODESIC", "SQUAREMETERS")
            if intersection_area / other_area >= 0.80:
                contained_masks.append((other_geometry, intersection_area))
        if len(contained_masks) < minimum_children:
            continue
        covered_geometry = None
        for contained_geometry, _ in contained_masks:
            overlap_geometry = geometry.intersect(contained_geometry, 4)
            covered_geometry = overlap_geometry if covered_geometry is None else covered_geometry.union(overlap_geometry)
        covered_area = covered_geometry.getArea("GEODESIC", "SQUAREMETERS") if covered_geometry else 0.0
        coverage = covered_area / area
        distinct_masks = any(
            first_geometry.disjoint(second_geometry)
            for index, (first_geometry, _) in enumerate(contained_masks)
            for second_geometry, _ in contained_masks[index + 1:]
        )
        if distinct_masks and minimum_coverage <= coverage <= maximum_coverage:
            rejected_ids.add(object_id)

    keep_field = "AFE_KEEP_POLYGON"
    selected_features = arcpy.CreateUniqueName("polygon_mask_selection", scratch_workspace)
    try:
        arcpy.management.AddField(input_features, keep_field, "SHORT")
        with arcpy.da.UpdateCursor(input_features, ["OID@", keep_field]) as cursor:
            for object_id, _ in cursor:
                cursor.updateRow([object_id, int(object_id not in rejected_ids)])
        field_delimiter = arcpy.AddFieldDelimiters(input_features, keep_field)
        arcpy.management.MakeFeatureLayer(input_features, selected_features, f"{field_delimiter} = 1")
        arcpy.management.CopyFeatures(selected_features, output_features)
        arcpy.management.DeleteField(output_features, keep_field)
    finally:
        if arcpy.Exists(selected_features):
            arcpy.management.Delete(selected_features)
    return len(rejected_ids)


def prepare_extraction_raster(source_imagery, messages, ensure_web_mercator_raster):
    spatial_reference = arcpy.Describe(source_imagery).spatialReference
    if getattr(spatial_reference, "type", "") == "Projected":
        messages.addMessage("Using the selected projected imagery layer directly for feature extraction.")
        return source_imagery
    return ensure_web_mercator_raster(source_imagery, "Feature extraction imagery", messages)
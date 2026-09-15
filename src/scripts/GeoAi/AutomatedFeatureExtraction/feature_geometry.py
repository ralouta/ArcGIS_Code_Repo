import arcpy

from validation_helpers import meters_to_spatial_units, square_meters_to_spatial_units


def clean_road_surfaces(
    input_features, output_features, profile, spatial_reference, scratch_workspace, messages,
):
    repaired_features = arcpy.CreateUniqueName("road_repaired", scratch_workspace)
    screened_features = arcpy.CreateUniqueName("road_screened", scratch_workspace)
    simplified_features = arcpy.CreateUniqueName("road_simplified", scratch_workspace)
    cleaned_features = arcpy.CreateUniqueName("road_cleaned", scratch_workspace)
    dissolved_features = arcpy.CreateUniqueName("road_dissolved", scratch_workspace)
    component_features = arcpy.CreateUniqueName("road_components", scratch_workspace)
    boundary_features = arcpy.CreateUniqueName("road_boundaries", scratch_workspace)
    collapsed_features = arcpy.CreateUniqueName("road_collapsed", scratch_workspace)
    mask_simplification = meters_to_spatial_units(
        profile["road_mask_simplification_m"], spatial_reference
    )
    minimum_part_area = square_meters_to_spatial_units(
        profile["road_minimum_part_area_sqm"], spatial_reference
    )
    maximum_width = meters_to_spatial_units(profile["road_maximum_width_m"], spatial_reference)
    minimum_width = meters_to_spatial_units(profile["road_minimum_width_m"], spatial_reference)
    connection_extension = meters_to_spatial_units(
        profile["road_connection_extension_m"], spatial_reference
    )
    connection_snap = meters_to_spatial_units(profile["road_connection_snap_m"], spatial_reference)
    try:
        messages.addMessage(
            "Running road-centerline QA: simplifying masks, removing small parts, and "
            "collapsing paired boundaries into observed centerlines..."
        )
        messages.addMessage("Road QA: copying SAM3 polygon masks...")
        arcpy.management.CopyFeatures(input_features, repaired_features)
        messages.addMessage("Road QA: repairing copied polygon masks...")
        arcpy.management.RepairGeometry(repaired_features, "DELETE_NULL", "ESRI")
        if not int(arcpy.management.GetCount(repaired_features)[0]):
            raise arcpy.ExecuteError("Road QA repair produced no valid polygon masks.")
        messages.addMessage("Road QA: screening masks by minimum geodesic area...")
        rejected_mask_count = filter_by_minimum_geodesic_area(
            repaired_features, screened_features, profile["minimum_area_sqm"], scratch_workspace
        )
        if rejected_mask_count:
            messages.addMessage(
                f"Rejected {rejected_mask_count:,} road fragment(s) below "
                f"{profile['minimum_area_sqm']:g} sq m."
            )
        messages.addMessage("Road QA: simplifying polygon masks...")
        arcpy.cartography.SimplifyPolygon(
            screened_features,
            simplified_features,
            "POINT_REMOVE",
            mask_simplification,
            minimum_area=minimum_part_area,
            error_option="RESOLVE_ERRORS",
        )
        arcpy.management.EliminatePolygonPart(
            in_features=simplified_features,
            out_feature_class=cleaned_features,
            condition="AREA",
            part_area=minimum_part_area,
            part_area_percent="0",
            part_option="ANY",
        )
        messages.addMessage("Road QA: dissolving touching road masks into observed components...")
        arcpy.analysis.PairwiseDissolve(
            cleaned_features, dissolved_features, multi_part="MULTI_PART"
        )
        arcpy.management.MultipartToSinglepart(dissolved_features, component_features)
        arcpy.management.AddField(component_features, "AFE_COMPONENT_ID", "LONG")
        arcpy.management.AddField(component_features, "ROAD_AREA_SQM", "DOUBLE")
        component_oid_field = arcpy.Describe(component_features).OIDFieldName
        arcpy.management.CalculateField(
            component_features, "AFE_COMPONENT_ID", f"!{component_oid_field}!", "PYTHON3"
        )
        arcpy.management.CalculateGeometryAttributes(
            component_features, [["ROAD_AREA_SQM", "AREA_GEODESIC"]], area_unit="SQUARE_METERS"
        )
        component_count = int(arcpy.management.GetCount(component_features)[0])
        messages.addMessage(
            f"Road QA: collapsing paired boundaries for {component_count:,} observed road component(s)..."
        )
        arcpy.management.PolygonToLine(
            component_features, boundary_features, "IGNORE_NEIGHBORS"
        )
        arcpy.cartography.CollapseDualLinesToCenterline(
            boundary_features, collapsed_features, maximum_width, minimum_width
        )
        if not int(arcpy.management.GetCount(collapsed_features)[0]):
            raise arcpy.ExecuteError("Road QA could not derive usable centerlines from road boundaries.")
        messages.addMessage(
            "Road QA: extending centerlines up to {0:g} m and snapping coincident endpoints..."
            .format(profile["road_connection_extension_m"])
        )
        arcpy.edit.ExtendLine(collapsed_features, connection_extension, "EXTENSION")
        arcpy.management.Integrate(collapsed_features, connection_snap)
        messages.addMessage("Road QA: assigning component widths to centerlines...")
        arcpy.analysis.SpatialJoin(
            collapsed_features, component_features, output_features,
            "JOIN_ONE_TO_ONE", "KEEP_COMMON", match_option="INTERSECT"
        )
        arcpy.management.AddField(output_features, "ROAD_WIDTH_M", "DOUBLE")
        arcpy.management.AddField(output_features, "ROAD_LENGTH_M", "DOUBLE")
        arcpy.management.AddField(output_features, "WIDTH_METHOD", "TEXT", field_length=64)
        arcpy.management.CalculateGeometryAttributes(
            output_features, [["ROAD_LENGTH_M", "LENGTH_GEODESIC"]], length_unit="METERS"
        )
        component_lengths = {}
        with arcpy.da.SearchCursor(output_features, ["AFE_COMPONENT_ID", "ROAD_LENGTH_M"]) as cursor:
            for component_id, length_m in cursor:
                component_lengths[component_id] = component_lengths.get(component_id, 0.0) + (length_m or 0.0)
        component_areas = {
            component_id: area_sqm
            for component_id, area_sqm in arcpy.da.SearchCursor(
                component_features, ["AFE_COMPONENT_ID", "ROAD_AREA_SQM"]
            )
        }
        with arcpy.da.UpdateCursor(
            output_features, ["AFE_COMPONENT_ID", "ROAD_WIDTH_M", "WIDTH_METHOD"]
        ) as cursor:
            for component_id, _, _ in cursor:
                length_m = component_lengths.get(component_id, 0.0)
                area_sqm = component_areas.get(component_id, 0.0)
                width_m = area_sqm / length_m if length_m else 0.0
                cursor.updateRow([component_id, width_m, "MaskAreaOverCenterlineLength"])
        messages.addMessage(
            "Road QA produced centerline candidates with observed-mask widths and bounded "
            "endpoint connections; ROAD_WIDTH_M is component mask area divided by total centerline length."
        )
    except Exception as error:
        messages.addErrorMessage(
            f"Road-centerline QA could not complete ({error}); no polygon fallback was published."
        )
        if arcpy.Exists(output_features):
            arcpy.management.Delete(output_features)
        raise
    finally:
        for dataset in (
            repaired_features, screened_features, simplified_features, cleaned_features,
            dissolved_features, component_features, boundary_features, collapsed_features,
        ):
            if arcpy.Exists(dataset):
                arcpy.management.Delete(dataset)


def filter_by_minimum_geodesic_area(
    input_features, output_features, minimum_area_sqm, scratch_workspace,
):
    keep_field = "AFE_QA_KEEP"
    selection_layer = arcpy.CreateUniqueName("qa_area_selection", scratch_workspace)
    rejected_count = 0
    try:
        arcpy.management.AddField(input_features, keep_field, "SHORT")
        with arcpy.da.UpdateCursor(input_features, ["SHAPE@", keep_field]) as cursor:
            for geometry, _ in cursor:
                area = geometry.getArea("GEODESIC", "SQUAREMETERS") if geometry else 0.0
                keep_mask = area >= minimum_area_sqm
                cursor.updateRow([geometry, int(keep_mask)])
                rejected_count += int(not keep_mask)
        field_delimiter = arcpy.AddFieldDelimiters(input_features, keep_field)
        arcpy.management.MakeFeatureLayer(input_features, selection_layer, f"{field_delimiter} = 1")
        arcpy.management.CopyFeatures(selection_layer, output_features)
        arcpy.management.DeleteField(output_features, keep_field)
    finally:
        if arcpy.Exists(selection_layer):
            arcpy.management.Delete(selection_layer)
    return rejected_count


def clean_agricultural_fields(
    input_features, output_features, profile, spatial_reference, scratch_workspace, messages,
):
    repaired_features = arcpy.CreateUniqueName("field_repaired", scratch_workspace)
    screened_features = arcpy.CreateUniqueName("field_screened", scratch_workspace)
    contracted_features = arcpy.CreateUniqueName("field_contracted", scratch_workspace)
    contracted_singlepart_features = arcpy.CreateUniqueName(
        "field_contracted_singlepart", scratch_workspace
    )
    cleaned_parts_features = arcpy.CreateUniqueName("field_cleaned_parts", scratch_workspace)
    cleaned_features = arcpy.CreateUniqueName("field_hole_filled", scratch_workspace)
    expanded_features = arcpy.CreateUniqueName("field_expanded", scratch_workspace)
    simplified_features = arcpy.CreateUniqueName("field_simplified", scratch_workspace)
    smoothed_features = arcpy.CreateUniqueName("field_smoothed", scratch_workspace)
    singlepart_features = arcpy.CreateUniqueName("field_singlepart", scratch_workspace)
    contraction_distance = meters_to_spatial_units(
        profile["field_contraction_m"], spatial_reference
    )
    hole_fill_area = square_meters_to_spatial_units(
        profile["field_hole_fill_sqm"], spatial_reference
    )
    boundary_simplification = meters_to_spatial_units(
        profile["field_boundary_simplification_m"], spatial_reference
    )
    boundary_smoothing = meters_to_spatial_units(
        profile["field_boundary_smoothing_m"], spatial_reference
    )
    try:
        messages.addMessage(
            "Running agricultural-field QA: repairing masks, removing small fragments, "
            "and applying parcel-scale boundary generalization..."
        )
        arcpy.management.CopyFeatures(input_features, repaired_features)
        arcpy.management.RepairGeometry(repaired_features, "DELETE_NULL", "ESRI")
        rejected_count = filter_by_minimum_geodesic_area(
            repaired_features,
            screened_features,
            profile["field_minimum_area_sqm"],
            scratch_workspace,
        )
        if rejected_count:
            messages.addMessage(
                f"Rejected {rejected_count:,} agricultural fragment(s) below "
                f"{profile['field_minimum_area_sqm']:g} sq m."
            )
        arcpy.analysis.PairwiseBuffer(
            screened_features, contracted_features, -contraction_distance, dissolve_option="NONE"
        )
        arcpy.management.RepairGeometry(contracted_features, "DELETE_NULL", "ESRI")
        if not int(arcpy.management.GetCount(contracted_features)[0]):
            raise arcpy.ExecuteError("Agricultural-field QA contraction removed all polygons.")
        arcpy.management.MultipartToSinglepart(
            contracted_features, contracted_singlepart_features
        )
        arcpy.management.EliminatePolygonPart(
            in_features=contracted_singlepart_features,
            out_feature_class=cleaned_parts_features,
            condition="PERCENT",
            part_area="0 SquareMeters",
            part_area_percent=profile["field_part_area_percent"],
            part_option="CONTAINED_ONLY",
        )
        arcpy.management.EliminatePolygonPart(
            in_features=cleaned_parts_features,
            out_feature_class=cleaned_features,
            condition="AREA",
            part_area=hole_fill_area,
            part_area_percent="0",
            part_option="CONTAINED_ONLY",
        )
        arcpy.analysis.PairwiseBuffer(
            cleaned_features, expanded_features, contraction_distance
        )
        arcpy.cartography.SimplifyPolygon(
            in_features=expanded_features,
            out_feature_class=simplified_features,
            algorithm="POINT_REMOVE",
            tolerance=boundary_simplification,
            minimum_area=0,
            error_option="RESOLVE_ERRORS",
        )
        arcpy.management.RepairGeometry(simplified_features, "DELETE_NULL", "ESRI")
        arcpy.cartography.SmoothPolygon(
            in_features=simplified_features,
            out_feature_class=smoothed_features,
            algorithm="PAEK",
            tolerance=boundary_smoothing,
            error_option="RESOLVE_ERRORS",
        )
        arcpy.management.RepairGeometry(smoothed_features, "DELETE_NULL", "ESRI")
        arcpy.management.MultipartToSinglepart(smoothed_features, singlepart_features)
        filter_by_minimum_geodesic_area(
            singlepart_features,
            output_features,
            profile["field_minimum_area_sqm"],
            scratch_workspace,
        )
        if not int(arcpy.management.GetCount(output_features)[0]):
            raise arcpy.ExecuteError("Agricultural-field QA produced no valid polygons.")
        messages.addMessage(
            "Agricultural-field QA applied a {0:g} m shrink-clean-expand pass, removed "
            "fragments below {1:g} sq m, split narrow field connections before restoring "
            "parcels, eliminated contained parts below {2:g}%, filled {3:g} sq m enclosed "
            "holes, simplified boundaries at {4:g} m, and smoothed remaining corners at {5:g} m."
            .format(
                profile["field_contraction_m"],
                profile["field_minimum_area_sqm"],
                profile["field_part_area_percent"],
                profile["field_hole_fill_sqm"],
                profile["field_boundary_simplification_m"],
                profile["field_boundary_smoothing_m"],
            )
        )
    except Exception as error:
        messages.addWarningMessage(
            f"Agricultural-field QA could not complete ({error}); retaining original field detections."
        )
        arcpy.management.CopyFeatures(input_features, output_features)
    finally:
        for dataset in (
            repaired_features, screened_features, contracted_features,
            contracted_singlepart_features, cleaned_parts_features, cleaned_features,
            expanded_features, simplified_features, smoothed_features, singlepart_features,
        ):
            if arcpy.Exists(dataset):
                arcpy.management.Delete(dataset)


def regularize_building_footprints(
    input_features,
    output_features,
    spatial_reference,
    scratch_workspace,
    messages,
):
    area_field = "REG_AREA"
    source_id_field = "AFE_SOURCE_ID"
    tolerance_bands = (
        (0, 50, 0.5),
        (50, 200, 1.0),
        (200, 500, 1.5),
        (500, 1000, 2.5),
        (1000, 4500, 3.5),
        (4500, None, 5.0),
    )
    building_layer = arcpy.CreateUniqueName("building_regularization")
    fallback_layer = arcpy.CreateUniqueName("building_regularization_fallback")
    deduplicated_features = arcpy.CreateUniqueName(
        "regularized_buildings_deduplicated", scratch_workspace
    )
    regularized_outputs = []

    try:
        arcpy.management.AddField(input_features, area_field, "DOUBLE")
        arcpy.management.AddField(input_features, source_id_field, "LONG")
        input_oid_field = arcpy.Describe(input_features).OIDFieldName
        arcpy.management.CalculateField(
            input_features, source_id_field, f"!{input_oid_field}!", "PYTHON3"
        )
        arcpy.management.CalculateGeometryAttributes(
            input_features,
            [[area_field, "AREA_GEODESIC"]],
            area_unit="SQUARE_METERS",
        )
        arcpy.management.MakeFeatureLayer(input_features, building_layer)

        for minimum_area, maximum_area, tolerance_meters in tolerance_bands:
            where_clause = f"{area_field} > {minimum_area}"
            if maximum_area is not None:
                where_clause += f" AND {area_field} <= {maximum_area}"
            arcpy.management.SelectLayerByAttribute(
                building_layer, "NEW_SELECTION", where_clause
            )
            selected_count = int(arcpy.management.GetCount(building_layer)[0])
            if selected_count == 0:
                continue

            messages.addMessage(
                f"Regularizing {selected_count} building footprint(s) with a "
                f"{tolerance_meters:g} meter tolerance..."
            )
            regularized_output = arcpy.CreateUniqueName(
                "regularized_buildings", scratch_workspace
            )
            regularized_outputs.append(regularized_output)
            arcpy.ddd.RegularizeBuildingFootprint(
                in_features=building_layer,
                out_feature_class=regularized_output,
                method="RIGHT_ANGLES",
                tolerance=meters_to_spatial_units(tolerance_meters, spatial_reference),
            )

        if not regularized_outputs:
            messages.addWarningMessage(
                "Building regularization produced no output; retaining the original "
                "SAM3 detections."
            )
            arcpy.management.CopyFeatures(input_features, output_features)
            return
        arcpy.management.Merge(regularized_outputs, output_features)
        regularized_ids = {
            source_id
            for (source_id,) in arcpy.da.SearchCursor(output_features, [source_id_field])
            if source_id is not None
        }
        input_count = int(arcpy.management.GetCount(input_features)[0])
        if len(regularized_ids) < input_count:
            arcpy.management.MakeFeatureLayer(input_features, fallback_layer)
            arcpy.management.SelectLayerByAttribute(
                fallback_layer,
                "NEW_SELECTION",
                f"{source_id_field} NOT IN ({', '.join(map(str, regularized_ids)) or '-1'})",
            )
            fallback_count = int(arcpy.management.GetCount(fallback_layer)[0])
            if fallback_count:
                messages.addWarningMessage(
                    f"Retaining {fallback_count} original building footprint(s) that "
                    "could not be regularized."
                )
                arcpy.management.Append(fallback_layer, output_features, "NO_TEST")
        arcpy.management.DeleteField(output_features, [area_field, source_id_field])
        duplicate_count = remove_contained_building_duplicates(
            output_features, deduplicated_features, scratch_workspace
        )
        if duplicate_count:
            messages.addMessage(
                f"Removed {duplicate_count:,} nested building footprint duplicate(s)."
            )
            arcpy.management.Delete(output_features)
            arcpy.management.CopyFeatures(deduplicated_features, output_features)
    finally:
        for dataset in (building_layer, fallback_layer, deduplicated_features):
            if arcpy.Exists(dataset):
                arcpy.management.Delete(dataset)
        for dataset in regularized_outputs:
            if arcpy.Exists(dataset):
                arcpy.management.Delete(dataset)


def remove_contained_building_duplicates(
    input_features, output_features, scratch_workspace, containment_threshold=0.90,
    minimum_area_ratio=1.20,
):
    candidates = []
    with arcpy.da.SearchCursor(input_features, ["OID@", "SHAPE@"]) as cursor:
        for object_id, geometry in cursor:
            area = geometry.getArea("GEODESIC", "SQUAREMETERS") if geometry else 0.0
            if area > 0:
                candidates.append((object_id, geometry, area))

    rejected_ids = set()
    for object_id, geometry, area in candidates:
        for other_id, other_geometry, other_area in candidates:
            if object_id == other_id or other_area < area * minimum_area_ratio:
                continue
            if geometry.disjoint(other_geometry):
                continue
            intersection_area = geometry.intersect(other_geometry, 4).getArea(
                "GEODESIC", "SQUAREMETERS"
            )
            if intersection_area / area >= containment_threshold:
                rejected_ids.add(object_id)
                break

    if not rejected_ids:
        arcpy.management.CopyFeatures(input_features, output_features)
        return 0

    keep_field = "AFE_BUILDING_KEEP"
    selection_layer = arcpy.CreateUniqueName("building_duplicate_selection", scratch_workspace)
    try:
        arcpy.management.AddField(input_features, keep_field, "SHORT")
        with arcpy.da.UpdateCursor(input_features, ["OID@", keep_field]) as cursor:
            for object_id, _ in cursor:
                cursor.updateRow([object_id, int(object_id not in rejected_ids)])
        field_delimiter = arcpy.AddFieldDelimiters(input_features, keep_field)
        arcpy.management.MakeFeatureLayer(input_features, selection_layer, f"{field_delimiter} = 1")
        arcpy.management.CopyFeatures(selection_layer, output_features)
        arcpy.management.DeleteField(output_features, keep_field)
    finally:
        if arcpy.Exists(selection_layer):
            arcpy.management.Delete(selection_layer)
    return len(rejected_ids)
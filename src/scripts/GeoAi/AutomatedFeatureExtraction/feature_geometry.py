import arcpy

from validation_helpers import meters_to_spatial_units, square_meters_to_spatial_units


def clean_road_surfaces(
    input_features, output_features, profile, spatial_reference, scratch_workspace, messages,
):
    repaired_features = arcpy.CreateUniqueName("road_repaired", scratch_workspace)
    screened_features = arcpy.CreateUniqueName("road_screened", scratch_workspace)
    contracted_features = arcpy.CreateUniqueName("road_contracted", scratch_workspace)
    dissolved_features = arcpy.CreateUniqueName("road_dissolved", scratch_workspace)
    expanded_features = arcpy.CreateUniqueName("road_expanded", scratch_workspace)
    hole_filled_features = arcpy.CreateUniqueName("road_hole_filled", scratch_workspace)
    smoothed_features = arcpy.CreateUniqueName("road_smoothed", scratch_workspace)
    final_features = arcpy.CreateUniqueName("road_final", scratch_workspace)
    contraction_distance = meters_to_spatial_units(
        profile["road_contraction_m"], spatial_reference
    )
    smoothing_tolerance = meters_to_spatial_units(
        profile["road_smoothing_m"], spatial_reference
    )
    hole_fill_area = square_meters_to_spatial_units(
        profile["road_hole_fill_sqm"], spatial_reference
    )
    try:
        messages.addMessage(
            "Running road-surface QA: repairing masks, removing small fragments, "
            "and applying conservative shrink-clean-expand cleanup..."
        )
        arcpy.management.CopyFeatures(input_features, repaired_features)
        arcpy.management.RepairGeometry(repaired_features, "DELETE_NULL", "ESRI")
        if not int(arcpy.management.GetCount(repaired_features)[0]):
            raise arcpy.ExecuteError("Road QA repair produced no valid polygon masks.")
        rejected_mask_count = filter_by_minimum_geodesic_area(
            repaired_features, screened_features, profile["minimum_area_sqm"], scratch_workspace
        )
        if rejected_mask_count:
            messages.addMessage(
                f"Rejected {rejected_mask_count:,} road fragment(s) below "
                f"{profile['minimum_area_sqm']:g} sq m."
            )
        arcpy.analysis.PairwiseBuffer(
            screened_features, contracted_features, -contraction_distance
        )
        arcpy.management.RepairGeometry(contracted_features, "DELETE_NULL", "ESRI")
        if not int(arcpy.management.GetCount(contracted_features)[0]):
            raise arcpy.ExecuteError("Road QA contraction removed all polygon masks.")
        arcpy.analysis.PairwiseDissolve(contracted_features, dissolved_features)
        arcpy.management.MultipartToSinglepart(dissolved_features, expanded_features)
        arcpy.analysis.PairwiseBuffer(expanded_features, hole_filled_features, contraction_distance)
        arcpy.management.EliminatePolygonPart(
            in_features=hole_filled_features,
            out_feature_class=smoothed_features,
            condition="AREA",
            part_area=hole_fill_area,
            part_area_percent="0",
            part_option="CONTAINED_ONLY",
        )
        arcpy.cartography.SmoothPolygon(
            in_features=smoothed_features,
            out_feature_class=final_features,
            algorithm="PAEK",
            tolerance=smoothing_tolerance,
            endpoint_option="FIXED_ENDPOINT",
            error_option="RESOLVE_ERRORS",
        )
        arcpy.management.RepairGeometry(final_features, "DELETE_NULL", "ESRI")
        filter_by_minimum_geodesic_area(
            final_features, output_features, profile["minimum_area_sqm"], scratch_workspace
        )
        if not int(arcpy.management.GetCount(output_features)[0]):
            raise arcpy.ExecuteError("Road QA smoothing produced no valid polygons.")
        messages.addMessage(
            "Road-surface QA applied a {0:g} m shrink-clean-expand pass, removed "
            "fragments below {1:g} sq m, filled {2:g} sq m enclosed holes, and "
            "applied {3:g} m smoothing."
            .format(
                profile["road_contraction_m"],
                profile["minimum_area_sqm"],
                profile["road_hole_fill_sqm"],
                profile["road_smoothing_m"],
            )
        )
    except Exception as error:
        messages.addWarningMessage(
            f"Road-surface QA could not complete ({error}); retaining original road detections."
        )
        arcpy.management.CopyFeatures(input_features, output_features)
    finally:
        for dataset in (
            repaired_features, screened_features, contracted_features, dissolved_features,
            expanded_features, hole_filled_features, smoothed_features, final_features,
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
    cleaned_features = arcpy.CreateUniqueName("field_hole_filled", scratch_workspace)
    expanded_features = arcpy.CreateUniqueName("field_expanded", scratch_workspace)
    smoothed_features = arcpy.CreateUniqueName("field_smoothed", scratch_workspace)
    contraction_distance = meters_to_spatial_units(
        profile["field_contraction_m"], spatial_reference
    )
    hole_fill_area = square_meters_to_spatial_units(
        profile["field_hole_fill_sqm"], spatial_reference
    )
    smoothing_tolerance = meters_to_spatial_units(
        profile["field_smoothing_m"], spatial_reference
    )
    try:
        messages.addMessage(
            "Running agricultural-field QA: repairing masks, removing small fragments, "
            "and applying conservative shrink-clean-expand cleanup..."
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
            screened_features, contracted_features, -contraction_distance
        )
        arcpy.management.RepairGeometry(contracted_features, "DELETE_NULL", "ESRI")
        if not int(arcpy.management.GetCount(contracted_features)[0]):
            raise arcpy.ExecuteError("Agricultural-field QA contraction removed all polygons.")
        arcpy.management.EliminatePolygonPart(
            in_features=contracted_features,
            out_feature_class=cleaned_features,
            condition="AREA",
            part_area=hole_fill_area,
            part_area_percent="0",
            part_option="CONTAINED_ONLY",
        )
        arcpy.analysis.PairwiseBuffer(
            cleaned_features, expanded_features, contraction_distance
        )
        arcpy.cartography.SmoothPolygon(
            in_features=expanded_features,
            out_feature_class=smoothed_features,
            algorithm="PAEK",
            tolerance=smoothing_tolerance,
            endpoint_option="FIXED_ENDPOINT",
            error_option="RESOLVE_ERRORS",
        )
        arcpy.management.RepairGeometry(smoothed_features, "DELETE_NULL", "ESRI")
        filter_by_minimum_geodesic_area(
            smoothed_features,
            output_features,
            profile["field_minimum_area_sqm"],
            scratch_workspace,
        )
        if not int(arcpy.management.GetCount(output_features)[0]):
            raise arcpy.ExecuteError("Agricultural-field QA produced no valid polygons.")
        messages.addMessage(
            "Agricultural-field QA applied a {0:g} m shrink-clean-expand pass, removed "
            "fragments below {1:g} sq m, filled {2:g} sq m enclosed holes, and applied "
            "{3:g} m boundary smoothing; separate fields remain separate."
            .format(
                profile["field_contraction_m"],
                profile["field_minimum_area_sqm"],
                profile["field_hole_fill_sqm"],
                profile["field_smoothing_m"],
            )
        )
    except Exception as error:
        messages.addWarningMessage(
            f"Agricultural-field QA could not complete ({error}); retaining original field detections."
        )
        arcpy.management.CopyFeatures(input_features, output_features)
    finally:
        for dataset in (
            repaired_features, screened_features, contracted_features, cleaned_features,
            expanded_features, smoothed_features,
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
    finally:
        for dataset in (building_layer, fallback_layer):
            if arcpy.Exists(dataset):
                arcpy.management.Delete(dataset)
        for dataset in regularized_outputs:
            if arcpy.Exists(dataset):
                arcpy.management.Delete(dataset)
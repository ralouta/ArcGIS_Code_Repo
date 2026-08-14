import arcpy


def run_damage_classification(
    target_features, similar_features, output_features, moderate_threshold,
    high_threshold, match_option, search_radius, messages, tool_version, output_field_names,
):
    messages.addMessage(f"Damage Assessment classifier version {tool_version}")
    messages.addMessage("Counting similar-embedding features for each target feature...")
    arcpy.analysis.SpatialJoin(
        target_features=target_features,
        join_features=similar_features,
        out_feature_class=output_features,
        join_operation="JOIN_ONE_TO_ONE",
        join_type="KEEP_ALL",
        field_mapping=build_field_mappings(target_features, output_field_names),
        match_option=match_option,
        search_radius=search_radius,
    )
    messages.addMessage("Repairing output target geometries...")
    before_repair = int(arcpy.management.GetCount(output_features)[0])
    arcpy.management.RepairGeometry(output_features, "DELETE_NULL", "ESRI")
    removed_count = before_repair - int(arcpy.management.GetCount(output_features)[0])
    if removed_count:
        messages.addWarningMessage(f"Repair Geometry removed {removed_count} feature(s) with null geometry.")

    add_output_fields(output_features)
    arcpy.management.CalculateGeometryAttributes(
        output_features, [["BLDG_AREA", "AREA_GEODESIC"]], area_unit="SQUARE_METERS"
    )
    invalid_object_ids = []
    with arcpy.da.UpdateCursor(output_features, ["OID@", "BLDG_AREA"]) as cursor:
        for object_id, area_sqm in cursor:
            if area_sqm is None or area_sqm <= 0:
                invalid_object_ids.append(object_id)
                cursor.deleteRow()
    if invalid_object_ids:
        object_id_preview = ", ".join(str(object_id) for object_id in invalid_object_ids[:10])
        suffix = "..." if len(invalid_object_ids) > 10 else ""
        messages.addWarningMessage(
            "Removed {0} output feature(s) with empty or zero-area geometry. Object IDs: {1}{2}".format(
                len(invalid_object_ids), object_id_preview, suffix
            )
        )
    messages.addMessage("Calculating embedding coverage within each target feature...")
    overlap_areas = calculate_overlap_areas(output_features, similar_features, messages)
    evidence_classes = (
        "No Matching Damage Evidence",
        "Low Damage Evidence",
        "Moderate Damage Evidence",
        "High Damage Evidence",
    )
    class_totals = dict.fromkeys(evidence_classes, 0)
    fields = ["Join_Count", "BLDG_AREA", "DMG_BID", "DMG_CLASS", "MATCH_CNT", "DMG_AREA", "COVER_PCT"]
    with arcpy.da.UpdateCursor(output_features, fields) as cursor:
        for row in cursor:
            damage_area = overlap_areas.get(row[2], 0.0)
            coverage_percent = min(100.0, (damage_area / row[1]) * 100.0)
            damage_class = classify_coverage(coverage_percent, moderate_threshold, high_threshold)
            row[3:] = [damage_class, row[0] or 0, damage_area, coverage_percent]
            cursor.updateRow(row)
            class_totals[damage_class] += 1
    messages.addMessage(
        "Coverage thresholds: no matching evidence = 0%; low damage = >0% to <{0:.1f}%; "
        "moderate damage = {0:.1f}% to <{1:.1f}%; high damage >= {1:.1f}%.".format(
            moderate_threshold, high_threshold
        )
    )
    for damage_class in evidence_classes:
        messages.addMessage(f"{damage_class}: {class_totals[damage_class]} features")
    messages.addWarningMessage(
        "These classes indicate relative image evidence, not confirmed structural damage. "
        "No Matching Damage Evidence may also mean the feature is outside the embedding analysis extent. "
        "Validate Moderate and High Damage Evidence against post-event imagery or field observations."
    )


def classify_coverage(coverage_percent, moderate_threshold, high_threshold):
    if coverage_percent <= 0:
        return "No Matching Damage Evidence"
    if coverage_percent >= high_threshold:
        return "High Damage Evidence"
    if coverage_percent >= moderate_threshold:
        return "Moderate Damage Evidence"
    return "Low Damage Evidence"


def calculate_overlap_areas(buildings, similar_features, messages):
    scratch_workspace = arcpy.env.scratchGDB
    intersections = arcpy.CreateUniqueName("damage_intersections", scratch_workspace)
    dissolved = arcpy.CreateUniqueName("damage_overlap_dissolved", scratch_workspace)
    overlap_areas = {}
    try:
        arcpy.analysis.PairwiseIntersect([buildings, similar_features], intersections, "ALL", None, "INPUT")
        if not int(arcpy.management.GetCount(intersections)[0]):
            messages.addWarningMessage("No embedding polygons overlap the building polygons.")
            return overlap_areas
        arcpy.management.Dissolve(intersections, dissolved, "DMG_BID")
        arcpy.management.AddField(dissolved, "DMG_AREA", "DOUBLE")
        arcpy.management.CalculateGeometryAttributes(
            dissolved, [["DMG_AREA", "AREA_GEODESIC"]], area_unit="SQUARE_METERS"
        )
        with arcpy.da.SearchCursor(dissolved, ["DMG_BID", "DMG_AREA"]) as cursor:
            for building_id, damage_area in cursor:
                overlap_areas[building_id] = damage_area or 0.0
    finally:
        for dataset in (intersections, dissolved):
            if arcpy.Exists(dataset):
                arcpy.management.Delete(dataset)
    return overlap_areas


def build_field_mappings(buildings, output_field_names):
    field_mappings = arcpy.FieldMappings()
    field_mappings.addTable(buildings)
    for index in range(field_mappings.fieldCount - 1, -1, -1):
        if field_mappings.getFieldMap(index).outputField.name.upper() in output_field_names:
            field_mappings.removeFieldMap(index)
    return field_mappings


def add_output_fields(feature_class):
    existing_fields = {field.name.upper() for field in arcpy.ListFields(feature_class)}
    for field_name, field_type, field_length in (
        ("DMG_CLASS", "TEXT", 30), ("MATCH_CNT", "LONG", None), ("DMG_BID", "LONG", None),
        ("BLDG_AREA", "DOUBLE", None), ("DMG_AREA", "DOUBLE", None), ("COVER_PCT", "DOUBLE", None),
    ):
        if field_name not in existing_fields:
            if field_type == "TEXT":
                arcpy.management.AddField(feature_class, field_name, field_type, field_length=field_length)
            else:
                arcpy.management.AddField(feature_class, field_name, field_type)
    oid_field = arcpy.Describe(feature_class).OIDFieldName
    arcpy.management.CalculateField(feature_class, "DMG_BID", f"!{oid_field}!", "PYTHON3")
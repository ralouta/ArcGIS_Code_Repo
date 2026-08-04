import arcpy


TOOL_VERSION = "2.0.0"
NO_MATCH_EVIDENCE = "No Matching Damage Evidence"
LOW_EVIDENCE = "Low Damage Evidence"
MODERATE_EVIDENCE = "Moderate Damage Evidence"
HIGH_EVIDENCE = "High Damage Evidence"
OUTPUT_FIELD_NAMES = {
    "JOIN_COUNT",
    "DMG_CLASS",
    "MATCH_CNT",
    "BLDG_AREA",
    "DMG_AREA",
    "COVER_PCT",
    "DMG_BID",
}


class Toolbox(object):
    def __init__(self):
        self.label = "Building Damage Assessment"
        self.alias = "buildingdamage"
        self.tools = [ClassifyBuildingDamage]


class ClassifyBuildingDamage(object):
    def __init__(self):
        self.label = "Classify Building Damage from Similar Embeddings"
        self.description = (
            "Spatially joins similar-embedding features to building polygons and "
            "classifies damage evidence from the percentage of each building covered by embedding polygons."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        buildings = arcpy.Parameter(
            displayName="Input Building Polygons",
            name="in_buildings",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        buildings.filter.list = ["Polygon"]

        similar_features = arcpy.Parameter(
            displayName="Similar Embedding Features",
            name="in_similar_features",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        similar_features.filter.list = ["Polygon"]

        output_features = arcpy.Parameter(
            displayName="Output Classified Buildings",
            name="out_buildings",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Output",
        )

        moderate_coverage_threshold = arcpy.Parameter(
            displayName="Moderate Damage Minimum Coverage (%)",
            name="moderate_coverage_threshold",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
        )
        moderate_coverage_threshold.value = 20.0

        high_coverage_threshold = arcpy.Parameter(
            displayName="High Damage Minimum Coverage (%)",
            name="high_coverage_threshold",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
        )
        high_coverage_threshold.value = 50.0

        match_option = arcpy.Parameter(
            displayName="Spatial Match Option",
            name="match_option",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        match_option.filter.type = "ValueList"
        match_option.filter.list = ["INTERSECT"]
        match_option.value = "INTERSECT"

        search_radius = arcpy.Parameter(
            displayName="Search Radius",
            name="search_radius",
            datatype="GPLinearUnit",
            parameterType="Optional",
            direction="Input",
        )
        search_radius.enabled = False

        return [
            buildings,
            similar_features,
            output_features,
            moderate_coverage_threshold,
            high_coverage_threshold,
            match_option,
            search_radius,
        ]

    def updateParameters(self, parameters):
        parameters[6].enabled = False
        return

    def updateMessages(self, parameters):
        moderate_threshold = float(parameters[3].value) if parameters[3].value is not None else None
        high_threshold = float(parameters[4].value) if parameters[4].value is not None else None
        if moderate_threshold is not None and not 0 < moderate_threshold < 100:
            parameters[3].setErrorMessage("Moderate coverage must be greater than 0 and less than 100.")
        if high_threshold is not None and not 0 < high_threshold <= 100:
            parameters[4].setErrorMessage("High coverage must be greater than 0 and at most 100.")
        if moderate_threshold is not None and high_threshold is not None and moderate_threshold >= high_threshold:
            parameters[4].setErrorMessage("High coverage must be greater than moderate coverage.")

        if parameters[5].valueAsText != "INTERSECT":
            parameters[5].setErrorMessage("Coverage classification requires INTERSECT.")
        return

    def execute(self, parameters, messages):
        buildings = parameters[0].valueAsText
        similar_features = parameters[1].valueAsText
        output_features = parameters[2].valueAsText
        moderate_coverage_threshold = float(parameters[3].value)
        high_coverage_threshold = float(parameters[4].value)
        match_option = parameters[5].valueAsText
        search_radius = parameters[6].valueAsText or None

        messages.addMessage(f"Building Damage Assessment version {TOOL_VERSION}")
        messages.addMessage("Counting similar-embedding features for each building...")
        field_mappings = _build_field_mappings(buildings)
        arcpy.analysis.SpatialJoin(
            target_features=buildings,
            join_features=similar_features,
            out_feature_class=output_features,
            join_operation="JOIN_ONE_TO_ONE",
            join_type="KEEP_ALL",
            field_mapping=field_mappings,
            match_option=match_option,
            search_radius=search_radius,
        )
        count_before_repair = int(arcpy.management.GetCount(output_features)[0])
        messages.addMessage("Repairing output building geometries...")
        arcpy.management.RepairGeometry(output_features, "DELETE_NULL", "ESRI")
        count_after_repair = int(arcpy.management.GetCount(output_features)[0])
        removed_by_repair = count_before_repair - count_after_repair
        if removed_by_repair:
            messages.addWarningMessage(
                f"Repair Geometry removed {removed_by_repair} building(s) with null geometry."
            )

        _add_output_fields(output_features)
        arcpy.management.CalculateGeometryAttributes(
            output_features,
            [["BLDG_AREA", "AREA_GEODESIC"]],
            area_unit="SQUARE_METERS",
        )

        invalid_area_oids = []
        with arcpy.da.UpdateCursor(output_features, ["OID@", "BLDG_AREA"]) as cursor:
            for object_id, area_sqm in cursor:
                if area_sqm is None or area_sqm <= 0:
                    invalid_area_oids.append(object_id)
                    cursor.deleteRow()

        if invalid_area_oids:
            object_id_preview = ", ".join(
                str(object_id) for object_id in invalid_area_oids[:20]
            )
            if len(invalid_area_oids) > 20:
                object_id_preview += ", ..."
            messages.addWarningMessage(
                "Excluded {0} building(s) with empty or zero-area geometry. "
                "Output object IDs before deletion: {1}".format(
                    len(invalid_area_oids), object_id_preview
                )
            )

        messages.addMessage("Calculating embedding coverage within each building...")
        overlap_areas = _calculate_overlap_areas(
            output_features, similar_features, messages
        )

        class_totals = {
            NO_MATCH_EVIDENCE: 0,
            LOW_EVIDENCE: 0,
            MODERATE_EVIDENCE: 0,
            HIGH_EVIDENCE: 0,
        }
        fields = [
            "Join_Count",
            "BLDG_AREA",
            "DMG_BID",
            "DMG_CLASS",
            "MATCH_CNT",
            "DMG_AREA",
            "COVER_PCT",
        ]
        with arcpy.da.UpdateCursor(output_features, fields) as cursor:
            for row in cursor:
                count = row[0] or 0
                area_sqm = row[1]
                damage_area_sqm = overlap_areas.get(row[2], 0.0)
                coverage_percent = min(100.0, (damage_area_sqm / area_sqm) * 100.0)
                damage_class = _classify_coverage(
                    coverage_percent,
                    moderate_coverage_threshold,
                    high_coverage_threshold,
                )

                row[3] = damage_class
                row[4] = count
                row[5] = damage_area_sqm
                row[6] = coverage_percent
                cursor.updateRow(row)
                class_totals[damage_class] += 1

        messages.addMessage(
            "Coverage thresholds: no matching evidence = 0%; low damage = >0% to <{0:.1f}%; "
            "moderate damage = {0:.1f}% to <{1:.1f}%; high damage >= {1:.1f}%.".format(
                moderate_coverage_threshold,
                high_coverage_threshold,
            )
        )
        for damage_class in (
            NO_MATCH_EVIDENCE,
            LOW_EVIDENCE,
            MODERATE_EVIDENCE,
            HIGH_EVIDENCE,
        ):
            messages.addMessage(f"{damage_class}: {class_totals[damage_class]} buildings")

        messages.addWarningMessage(
            "These classes indicate relative image evidence, not confirmed structural damage. "
            "No Matching Damage Evidence may also mean the building is outside the embedding analysis extent. "
            "Validate Moderate and High Damage Evidence against post-event imagery or field observations."
        )

        parameters[2].value = output_features


def _classify_coverage(coverage_percent, moderate_threshold, high_threshold):
    if coverage_percent <= 0:
        return NO_MATCH_EVIDENCE
    if coverage_percent >= high_threshold:
        return HIGH_EVIDENCE
    if coverage_percent >= moderate_threshold:
        return MODERATE_EVIDENCE
    return LOW_EVIDENCE


def _calculate_overlap_areas(buildings, similar_features, messages):
    scratch_workspace = arcpy.env.scratchGDB
    intersections = arcpy.CreateUniqueName("damage_intersections", scratch_workspace)
    dissolved = arcpy.CreateUniqueName("damage_overlap_dissolved", scratch_workspace)
    overlap_areas = {}

    try:
        arcpy.analysis.PairwiseIntersect(
            [buildings, similar_features], intersections, "ALL", None, "INPUT"
        )
        if int(arcpy.management.GetCount(intersections)[0]) == 0:
            messages.addWarningMessage("No embedding polygons overlap the building polygons.")
            return overlap_areas

        arcpy.management.Dissolve(intersections, dissolved, "DMG_BID")
        arcpy.management.AddField(dissolved, "DMG_AREA", "DOUBLE")
        arcpy.management.CalculateGeometryAttributes(
            dissolved,
            [["DMG_AREA", "AREA_GEODESIC"]],
            area_unit="SQUARE_METERS",
        )
        with arcpy.da.SearchCursor(dissolved, ["DMG_BID", "DMG_AREA"]) as cursor:
            for building_id, damage_area_sqm in cursor:
                overlap_areas[building_id] = damage_area_sqm or 0.0
    finally:
        for dataset in (intersections, dissolved):
            if arcpy.Exists(dataset):
                arcpy.management.Delete(dataset)

    return overlap_areas


def _build_field_mappings(buildings):
    field_mappings = arcpy.FieldMappings()
    field_mappings.addTable(buildings)

    for index in range(field_mappings.fieldCount - 1, -1, -1):
        field_name = field_mappings.getFieldMap(index).outputField.name.upper()
        if field_name in OUTPUT_FIELD_NAMES:
            field_mappings.removeFieldMap(index)

    return field_mappings


def _add_output_fields(feature_class):
    existing_fields = {field.name.upper() for field in arcpy.ListFields(feature_class)}
    field_definitions = [
        ("DMG_CLASS", "TEXT", 30),
        ("MATCH_CNT", "LONG", None),
        ("DMG_BID", "LONG", None),
        ("BLDG_AREA", "DOUBLE", None),
        ("DMG_AREA", "DOUBLE", None),
        ("COVER_PCT", "DOUBLE", None),
    ]

    for field_name, field_type, field_length in field_definitions:
        if field_name in existing_fields:
            continue
        if field_type == "TEXT":
            arcpy.management.AddField(
                feature_class, field_name, field_type, field_length=field_length
            )
        else:
            arcpy.management.AddField(feature_class, field_name, field_type)

    oid_field = arcpy.Describe(feature_class).OIDFieldName
    arcpy.management.CalculateField(feature_class, "DMG_BID", f"!{oid_field}!")

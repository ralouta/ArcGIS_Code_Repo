import math
import statistics

import arcpy


LOW_EVIDENCE = "Low / No Damage Evidence"
POSSIBLE_DAMAGE = "Potential Damage"
HIGH_EVIDENCE = "High Damage Evidence"
INVALID_GEOMETRY = "Invalid / Empty Geometry"
OUTPUT_FIELD_NAMES = {
    "JOIN_COUNT",
    "DMG_CLASS",
    "MATCH_CNT",
    "BLDG_AREA",
    "EVID_SCORE",
    "SCORE_MED",
    "SCORE_MAD",
    "HIGH_THR",
    "ROBUST_Z",
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
            "screens damage evidence using area-normalized match density and robust statistics."
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

        output_features = arcpy.Parameter(
            displayName="Output Classified Buildings",
            name="out_buildings",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Output",
        )

        low_evidence_max = arcpy.Parameter(
            displayName="Maximum Match Count for Low / No Damage Evidence",
            name="low_evidence_max",
            datatype="GPLong",
            parameterType="Optional",
            direction="Input",
        )
        low_evidence_max.value = 1

        robust_multiplier = arcpy.Parameter(
            displayName="High Evidence Threshold (Scaled MADs Above Median)",
            name="robust_multiplier",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
        )
        robust_multiplier.value = 3.0

        match_option = arcpy.Parameter(
            displayName="Spatial Match Option",
            name="match_option",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        match_option.filter.type = "ValueList"
        match_option.filter.list = [
            "HAVE_THEIR_CENTER_IN",
            "INTERSECT",
            "CONTAINS",
            "WITHIN_A_DISTANCE",
        ]
        match_option.value = "HAVE_THEIR_CENTER_IN"

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
            low_evidence_max,
            robust_multiplier,
            match_option,
            search_radius,
        ]

    def updateParameters(self, parameters):
        parameters[6].enabled = parameters[5].valueAsText == "WITHIN_A_DISTANCE"
        return

    def updateMessages(self, parameters):
        if parameters[3].value is not None and int(parameters[3].value) < 0:
            parameters[3].setErrorMessage("The low-evidence match count must be zero or greater.")

        if parameters[4].value is not None and float(parameters[4].value) < 0:
            parameters[4].setErrorMessage("The scaled-MAD multiplier must be zero or greater.")

        if parameters[5].valueAsText == "WITHIN_A_DISTANCE" and not parameters[6].valueAsText:
            parameters[6].setErrorMessage("A search radius is required for WITHIN_A_DISTANCE.")
        return

    def execute(self, parameters, messages):
        buildings = parameters[0].valueAsText
        similar_features = parameters[1].valueAsText
        output_features = parameters[2].valueAsText
        low_evidence_max = int(parameters[3].value)
        robust_multiplier = float(parameters[4].value)
        match_option = parameters[5].valueAsText
        search_radius = parameters[6].valueAsText or None

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

        observations = []
        invalid_geometry_oids = []
        with arcpy.da.SearchCursor(
            output_features, ["OID@", "Join_Count", "SHAPE@"]
        ) as cursor:
            for object_id, count, geometry in cursor:
                count = count or 0
                area_sqm = _get_area_sqm(geometry)
                if area_sqm is None:
                    invalid_geometry_oids.append(object_id)
                    continue
                score = _calculate_evidence_score(count, area_sqm)
                observations.append((count, area_sqm, score))

        if invalid_geometry_oids:
            messages.addWarningMessage(
                "Excluded {0} building(s) with null, empty, or zero-area geometry from the statistics. "
                "Output object IDs: {1}".format(
                    len(invalid_geometry_oids),
                    ", ".join(str(object_id) for object_id in invalid_geometry_oids),
                )
            )

        candidate_scores = [
            score for count, _, score in observations if count > low_evidence_max
        ]
        if candidate_scores:
            score_median, scaled_mad, high_threshold = _robust_threshold(
                candidate_scores, robust_multiplier
            )
        else:
            score_median = 0.0
            scaled_mad = 0.0
            high_threshold = math.inf
            messages.addWarningMessage(
                "No buildings exceeded the low-evidence cutoff; all buildings will be classified as Low / No Damage Evidence."
            )

        if 0 < len(candidate_scores) < 5:
            messages.addWarningMessage(
                "Fewer than five buildings exceeded the low-evidence cutoff. Treat the statistical classes as provisional."
            )
        if candidate_scores and scaled_mad == 0:
            messages.addWarningMessage(
                "Candidate scores have no robust spread; no building can be separated as High Damage Evidence."
            )

        _add_output_fields(output_features)

        class_totals = {
            LOW_EVIDENCE: 0,
            POSSIBLE_DAMAGE: 0,
            HIGH_EVIDENCE: 0,
            INVALID_GEOMETRY: 0,
        }
        fields = [
            "Join_Count",
            "SHAPE@",
            "DMG_CLASS",
            "MATCH_CNT",
            "BLDG_AREA",
            "EVID_SCORE",
            "SCORE_MED",
            "SCORE_MAD",
            "HIGH_THR",
            "ROBUST_Z",
        ]
        with arcpy.da.UpdateCursor(output_features, fields) as cursor:
            for row in cursor:
                count = row[0] or 0
                geometry = row[1]
                area_sqm = _get_area_sqm(geometry)
                if area_sqm is None:
                    score = None
                    damage_class = INVALID_GEOMETRY
                    robust_z = None
                else:
                    score = _calculate_evidence_score(count, area_sqm)
                    damage_class = _classify_score(
                        count, score, low_evidence_max, high_threshold, scaled_mad
                    )
                    robust_z = (
                        (score - score_median) / scaled_mad
                        if count > low_evidence_max and scaled_mad > 0
                        else None
                    )

                row[2] = damage_class
                row[3] = count
                row[4] = area_sqm
                row[5] = score
                row[6] = score_median
                row[7] = scaled_mad
                row[8] = None if math.isinf(high_threshold) else high_threshold
                row[9] = robust_z
                cursor.updateRow(row)
                class_totals[damage_class] += 1

        messages.addMessage(
            "Screening thresholds: low evidence <= {0} matches; high evidence score > {1}. "
            "Candidate median = {2:.3f}, scaled MAD = {3:.3f}.".format(
                low_evidence_max,
                "N/A" if math.isinf(high_threshold) else f"{high_threshold:.3f}",
                score_median,
                scaled_mad,
            )
        )
        for damage_class in (
            LOW_EVIDENCE,
            POSSIBLE_DAMAGE,
            HIGH_EVIDENCE,
            INVALID_GEOMETRY,
        ):
            messages.addMessage(f"{damage_class}: {class_totals[damage_class]} buildings")

        messages.addWarningMessage(
            "These classes indicate relative image evidence, not confirmed structural damage. "
            "Validate High Damage Evidence buildings against post-event imagery or field observations."
        )

        parameters[2].value = output_features


def _get_area_sqm(geometry):
    if geometry is None or geometry.isEmpty:
        return None
    area_sqm = geometry.getArea("GEODESIC", "SQUAREMETERS")
    return area_sqm if area_sqm > 0 else None


def _calculate_evidence_score(count, area_sqm):
    if area_sqm <= 0:
        return 0.0
    return (count / area_sqm) * 100.0


def _robust_threshold(scores, multiplier):
    score_median = statistics.median(scores)
    mad = statistics.median(abs(score - score_median) for score in scores)
    scaled_mad = 1.4826 * mad
    return score_median, scaled_mad, score_median + (multiplier * scaled_mad)


def _classify_score(count, score, low_evidence_max, high_threshold, scaled_mad):
    if count <= low_evidence_max:
        return LOW_EVIDENCE
    if scaled_mad > 0 and score > high_threshold:
        return HIGH_EVIDENCE
    return POSSIBLE_DAMAGE


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
        ("BLDG_AREA", "DOUBLE", None),
        ("EVID_SCORE", "DOUBLE", None),
        ("SCORE_MED", "DOUBLE", None),
        ("SCORE_MAD", "DOUBLE", None),
        ("HIGH_THR", "DOUBLE", None),
        ("ROBUST_Z", "DOUBLE", None),
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

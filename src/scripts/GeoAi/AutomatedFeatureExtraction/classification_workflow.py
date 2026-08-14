import math

import arcpy


def find_classified_similar_features(
    embedding_features,
    target_features,
    sample_points,
    class_field,
    feature_type,
    output_features,
    seed_output_features,
    threshold,
    scratch_workspace,
    messages,
    class_value_label,
    select_feature_embedding_queries,
    sql_literal,
):
    class_values = []
    with arcpy.da.SearchCursor(sample_points, [class_field]) as cursor:
        for (value,) in cursor:
            if value is not None and str(value).strip() and value not in class_values:
                class_values.append(value)
    class_values.sort(key=lambda value: str(value).casefold())
    if not class_values:
        raise arcpy.ExecuteError("The selected class field has no populated values.")
    class_labels = {
        value: class_value_label(sample_points, class_field, value)
        for value in class_values
    }
    sample_layer = arcpy.CreateUniqueName("classified_example_points", scratch_workspace)
    class_outputs = []
    seed_outputs = []
    try:
        arcpy.management.MakeFeatureLayer(sample_points, sample_layer)
        field_delimiter = arcpy.AddFieldDelimiters(sample_points, class_field)
        field_type = next(
            field.type for field in arcpy.ListFields(sample_points) if field.name == class_field
        )
        for index, value in enumerate(class_values, start=1):
            class_label = class_labels[value]
            where_clause = f"{field_delimiter} = {sql_literal(value, field_type)}"
            arcpy.management.SelectLayerByAttribute(sample_layer, "NEW_SELECTION", where_clause)
            class_samples = arcpy.CreateUniqueName("class_examples", scratch_workspace)
            query_features = None
            seed_features = None
            class_output = arcpy.CreateUniqueName("class_similar", scratch_workspace)
            try:
                arcpy.management.CopyFeatures(sample_layer, class_samples)
                messages.addMessage(
                    f"Preparing similarity evidence for class '{class_label}' "
                    f"({index} of {len(class_values)})..."
                )
                query_features, seed_features = select_feature_embedding_queries(
                    embedding_features,
                    target_features,
                    class_samples,
                    scratch_workspace,
                    messages,
                    class_label,
                    feature_type == "Roads",
                )
                messages.addMessage(
                    f"Finding matches for class '{class_label}' ({index} of {len(class_values)})..."
                )
                arcpy.geoai.FindSimilarFeaturesUsingEmbeddings(
                    embedding_features=embedding_features,
                    query_features=query_features,
                    out_embeddings_feature_class=class_output,
                    threshold=threshold,
                )
                arcpy.management.AddField(class_output, "AFE_CLASS", "TEXT", field_length=255)
                arcpy.management.CalculateField(class_output, "AFE_CLASS", repr(class_label), "PYTHON3")
                arcpy.management.AddField(seed_features, "AFE_CLASS", "TEXT", field_length=255)
                arcpy.management.CalculateField(seed_features, "AFE_CLASS", repr(class_label), "PYTHON3")
                class_outputs.append(class_output)
                seed_outputs.append(seed_features)
                seed_features = None
            finally:
                for dataset in (class_samples, query_features, seed_features):
                    if dataset and arcpy.Exists(dataset):
                        arcpy.management.Delete(dataset)
        arcpy.management.Merge(class_outputs, output_features)
        arcpy.management.Merge(seed_outputs, seed_output_features)
    finally:
        if arcpy.Exists(sample_layer):
            arcpy.management.Delete(sample_layer)
        for dataset in class_outputs + seed_outputs:
            if arcpy.Exists(dataset):
                arcpy.management.Delete(dataset)


def classify_target_features(
    target_features, similar_features, seed_features, output_features, scratch_workspace, messages,
):
    target_id_field = "AFE_TARGET_ID"
    target_area_field = "AFE_AREA_SQM"
    evidence_area_field = "AFE_EVID_SQM"
    arcpy.management.CopyFeatures(target_features, output_features)
    existing_fields = {field.name.upper() for field in arcpy.ListFields(output_features)}
    if target_id_field not in existing_fields:
        arcpy.management.AddField(output_features, target_id_field, "LONG")
    if "AUTO_CLASS" not in existing_fields:
        arcpy.management.AddField(output_features, "AUTO_CLASS", "TEXT", field_length=255)
    if "CLASS_COV_PCT" not in existing_fields:
        arcpy.management.AddField(output_features, "CLASS_COV_PCT", "DOUBLE")
    if "CLASS_REASON" not in existing_fields:
        arcpy.management.AddField(output_features, "CLASS_REASON", "TEXT", field_length=255)
    if "EVIDENCE_METRIC" not in existing_fields:
        arcpy.management.AddField(output_features, "EVIDENCE_METRIC", "TEXT", field_length=32)
    if target_area_field not in existing_fields:
        arcpy.management.AddField(output_features, target_area_field, "DOUBLE")
    oid_field = arcpy.Describe(output_features).OIDFieldName
    arcpy.management.CalculateField(output_features, target_id_field, f"!{oid_field}!", "PYTHON3")
    arcpy.management.CalculateGeometryAttributes(
        output_features, [[target_area_field, "AREA_GEODESIC"]], area_unit="SQUARE_METERS"
    )
    evidence_by_target = {}
    for evidence_features in (similar_features, seed_features):
        intersections = arcpy.CreateUniqueName("class_intersections", scratch_workspace)
        try:
            arcpy.analysis.PairwiseIntersect(
                [output_features, evidence_features], intersections, "ALL", None, "INPUT"
            )
            if int(arcpy.management.GetCount(intersections)[0]):
                arcpy.management.AddField(intersections, evidence_area_field, "DOUBLE")
                arcpy.management.CalculateGeometryAttributes(
                    intersections, [[evidence_area_field, "AREA_GEODESIC"]], area_unit="SQUARE_METERS"
                )
                with arcpy.da.SearchCursor(
                    intersections, [target_id_field, "AFE_CLASS", evidence_area_field]
                ) as cursor:
                    for target_id, class_value, evidence_area in cursor:
                        if target_id is None or not class_value:
                            continue
                        target_evidence = evidence_by_target.setdefault(target_id, {})
                        target_evidence[class_value] = (
                            target_evidence.get(class_value, 0.0) + (evidence_area or 0.0)
                        )
        finally:
            if arcpy.Exists(intersections):
                arcpy.management.Delete(intersections)

    classified_count = 0
    with arcpy.da.UpdateCursor(
        output_features,
        [target_id_field, target_area_field, "AUTO_CLASS", "CLASS_COV_PCT", "CLASS_REASON", "EVIDENCE_METRIC"],
    ) as cursor:
        for target_id, target_area, class_value, coverage_percent, class_reason, evidence_metric in cursor:
            class_evidence = evidence_by_target.get(target_id, {})
            if class_evidence:
                ranked_classes = sorted(
                    class_evidence.items(), key=lambda item: (-item[1], str(item[0]).casefold())
                )
                class_value, evidence_area = ranked_classes[0]
                coverage_percent = min(100.0, (evidence_area / target_area) * 100.0) if target_area else 0.0
                tied_classes = [
                    str(value) for value, area in ranked_classes
                    if math.isclose(area, evidence_area, rel_tol=1e-9, abs_tol=1e-6)
                ]
                if len(tied_classes) > 1:
                    class_value = "Ambiguous"
                    class_reason = "Equal evidence for: " + ", ".join(tied_classes)
                else:
                    class_reason = "Strongest overlapping class evidence"
                    classified_count += 1
            else:
                class_value = "Unclassified"
                coverage_percent = 0.0
                class_reason = "No overlapping class evidence"
            cursor.updateRow([
                target_id,
                target_area,
                class_value,
                coverage_percent,
                class_reason,
                "AreaCoveragePercent",
            ])
    arcpy.management.DeleteField(output_features, [target_id_field, target_area_field])
    messages.addMessage(
        f"Classified {classified_count} of {int(arcpy.management.GetCount(output_features)[0])} target feature(s)."
    )
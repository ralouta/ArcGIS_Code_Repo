import arcpy


def select_damage_queries(target_features, sample_points, feature_type, scratch_workspace, messages):
    if feature_type == "Roads":
        return create_road_damage_queries(target_features, sample_points, scratch_workspace, messages)

    target_layer = arcpy.CreateUniqueName("damage_target_selection")
    query_features = arcpy.CreateUniqueName("damage_queries", scratch_workspace)
    try:
        arcpy.management.MakeFeatureLayer(target_features, target_layer)
        arcpy.management.SelectLayerByLocation(
            target_layer, "INTERSECT", sample_points, None, "NEW_SELECTION"
        )
        selected_count = int(arcpy.management.GetCount(target_layer)[0])
        if selected_count < 6:
            raise arcpy.ExecuteError(
                "Damage example points must intersect at least 6 unique target features; "
                f"{selected_count} unique feature(s) were selected."
            )
        arcpy.management.CopyFeatures(target_layer, query_features)
        messages.addMessage(f"Using {selected_count} target features as post-event damage examples.")
    finally:
        if arcpy.Exists(target_layer):
            arcpy.management.Delete(target_layer)
    return query_features


def select_embedding_queries(embedding_features, sample_points, scratch_workspace, messages):
    embedding_layer = arcpy.CreateUniqueName("embedding_query_selection")
    query_features = arcpy.CreateUniqueName("embedding_queries", scratch_workspace)
    try:
        arcpy.management.MakeFeatureLayer(embedding_features, embedding_layer)
        arcpy.management.SelectLayerByLocation(
            embedding_layer, "INTERSECT", sample_points, None, "NEW_SELECTION"
        )
        selected_count = int(arcpy.management.GetCount(embedding_layer)[0])
        if selected_count < 6:
            raise arcpy.ExecuteError(
                "Example points must intersect at least 6 unique embedding cells; "
                f"{selected_count} cell(s) were selected."
            )
        arcpy.management.CopyFeatures(embedding_layer, query_features)
        messages.addMessage(f"Using {selected_count} embedding cell(s) as similarity examples.")
        return query_features
    except Exception:
        if arcpy.Exists(query_features):
            arcpy.management.Delete(query_features)
        raise
    finally:
        if arcpy.Exists(embedding_layer):
            arcpy.management.Delete(embedding_layer)


def select_feature_embedding_queries(
    embedding_features, target_features, sample_points, scratch_workspace, messages,
    class_value=None, is_road=False,
):
    if is_road:
        return select_road_feature_embedding_queries(
            embedding_features, target_features, sample_points, scratch_workspace, messages, class_value
        )
    target_layer = arcpy.CreateUniqueName("classification_target_selection")
    embedding_layer = arcpy.CreateUniqueName("classification_embedding_selection")
    query_features = arcpy.CreateUniqueName("classification_embedding_queries", scratch_workspace)
    seed_features = arcpy.CreateUniqueName("classification_target_seeds", scratch_workspace)
    try:
        arcpy.management.MakeFeatureLayer(target_features, target_layer)
        arcpy.management.SelectLayerByLocation(
            target_layer, "INTERSECT", sample_points, None, "NEW_SELECTION"
        )
        target_count = int(arcpy.management.GetCount(target_layer)[0])
        point_count = int(arcpy.management.GetCount(sample_points)[0])
        class_label = f"Class '{class_value}'" if class_value is not None else "Examples"
        messages.addMessage(
            f"{class_label}: {point_count} example point(s) selected {target_count} intersecting target feature(s)."
        )
        if target_count < 6:
            raise arcpy.ExecuteError(
                f"{class_label} needs example points that intersect at least 6 unique "
                f"target features; {point_count} point(s) selected {target_count} target feature(s)."
            )
        arcpy.management.CopyFeatures(target_layer, seed_features)
        arcpy.management.MakeFeatureLayer(embedding_features, embedding_layer)
        arcpy.management.SelectLayerByLocation(
            embedding_layer, "INTERSECT", target_layer, None, "NEW_SELECTION"
        )
        cell_count = int(arcpy.management.GetCount(embedding_layer)[0])
        if cell_count < 6:
            raise arcpy.ExecuteError(
                "The selected example target features must intersect at least 6 unique embedding cells; "
                f"{cell_count} cell(s) were selected."
            )
        arcpy.management.CopyFeatures(embedding_layer, query_features)
        messages.addMessage(
            f"Using {target_count} sampled target feature(s) and {cell_count} intersecting "
            "embedding cell(s) as similarity examples."
        )
        return query_features, seed_features
    except Exception:
        for dataset in (query_features, seed_features):
            if arcpy.Exists(dataset):
                arcpy.management.Delete(dataset)
        raise
    finally:
        for layer in (target_layer, embedding_layer):
            if arcpy.Exists(layer):
                arcpy.management.Delete(layer)


def select_road_feature_embedding_queries(
    embedding_features, target_features, sample_points, scratch_workspace, messages, class_value,
):
    sample_layer = arcpy.CreateUniqueName("road_classification_samples")
    target_layer = arcpy.CreateUniqueName("road_classification_targets")
    embedding_layer = arcpy.CreateUniqueName("road_classification_embeddings")
    sample_regions = arcpy.CreateUniqueName("road_classification_regions", scratch_workspace)
    query_features = arcpy.CreateUniqueName("road_embedding_queries", scratch_workspace)
    seed_features = arcpy.CreateUniqueName("road_target_seeds", scratch_workspace)
    class_label = f"Class '{class_value}'" if class_value is not None else "Road examples"
    try:
        arcpy.management.MakeFeatureLayer(sample_points, sample_layer)
        sample_count = int(arcpy.management.GetCount(sample_layer)[0])
        if sample_count < 6:
            raise arcpy.ExecuteError(f"{class_label} needs at least 6 example points; {sample_count} point(s) were provided.")
        arcpy.management.SelectLayerByLocation(
            sample_layer, "WITHIN_A_DISTANCE", target_features, "10 Meters", "NEW_SELECTION"
        )
        nearby_count = int(arcpy.management.GetCount(sample_layer)[0])
        if nearby_count < sample_count:
            messages.addWarningMessage(
                f"{class_label}: {sample_count - nearby_count} example point(s) are more than "
                "10 meters from an inferred road. They remain in the embedding query because "
                "SAM3 road masks are candidate evidence, not ground truth."
            )
        arcpy.management.SelectLayerByAttribute(sample_layer, "CLEAR_SELECTION")
        arcpy.analysis.PairwiseBuffer(sample_layer, sample_regions, "10 Meters", dissolve_option="NONE")
        arcpy.management.MakeFeatureLayer(target_features, target_layer)
        arcpy.management.SelectLayerByLocation(target_layer, "INTERSECT", sample_regions, None, "NEW_SELECTION")
        arcpy.management.CopyFeatures(target_layer, seed_features)
        arcpy.management.MakeFeatureLayer(embedding_features, embedding_layer)
        arcpy.management.SelectLayerByLocation(embedding_layer, "INTERSECT", sample_regions, None, "NEW_SELECTION")
        cell_count = int(arcpy.management.GetCount(embedding_layer)[0])
        if cell_count < 6:
            raise arcpy.ExecuteError(f"{class_label} needs at least 6 intersecting embedding cells; {cell_count} cell(s) were selected.")
        arcpy.management.CopyFeatures(embedding_layer, query_features)
        messages.addMessage(
            f"{class_label}: using {sample_count} point-centered road region(s) and {cell_count} embedding cell(s) as similarity examples."
        )
        return query_features, seed_features
    except Exception:
        for dataset in (query_features, seed_features):
            if arcpy.Exists(dataset):
                arcpy.management.Delete(dataset)
        raise
    finally:
        for dataset in (sample_layer, target_layer, embedding_layer, sample_regions):
            if arcpy.Exists(dataset):
                arcpy.management.Delete(dataset)


def create_road_damage_queries(target_features, sample_points, scratch_workspace, messages):
    sample_count = int(arcpy.management.GetCount(sample_points)[0])
    if sample_count < 6:
        raise arcpy.ExecuteError(
            "Road damage examples require at least 6 point features; "
            f"{sample_count} point feature(s) were provided."
        )
    sample_layer = arcpy.CreateUniqueName("road_damage_sample_qa")
    query_features = arcpy.CreateUniqueName("road_damage_queries", scratch_workspace)
    try:
        arcpy.management.MakeFeatureLayer(sample_points, sample_layer)
        arcpy.management.SelectLayerByLocation(sample_layer, "INTERSECT", target_features, None, "NEW_SELECTION")
        intersecting_count = int(arcpy.management.GetCount(sample_layer)[0])
        arcpy.management.SelectLayerByLocation(
            sample_layer, "WITHIN_A_DISTANCE", target_features, "10 Meters", "NEW_SELECTION"
        )
        valid_count = int(arcpy.management.GetCount(sample_layer)[0])
        nearby_count = valid_count - intersecting_count
        rejected_count = sample_count - valid_count
        messages.addMessage(
            "Road sample QA: "
            f"{intersecting_count} on inferred roads, {nearby_count} within 10 meters, {rejected_count} farther away."
        )
        if rejected_count:
            messages.addWarningMessage(
                f"Ignored {rejected_count} road damage point(s) more than 10 meters from an inferred road."
            )
        if valid_count < 6:
            raise arcpy.ExecuteError(
                "At least 6 road damage points must intersect or be within 10 meters "
                f"of an inferred road; {valid_count} valid point(s) remain."
            )
        arcpy.analysis.PairwiseBuffer(sample_layer, query_features, "10 Meters", dissolve_option="NONE")
        messages.addMessage(f"Using {valid_count} point-centered road regions as post-event damage examples.")
        return query_features
    except Exception:
        if arcpy.Exists(query_features):
            arcpy.management.Delete(query_features)
        raise
    finally:
        if arcpy.Exists(sample_layer):
            arcpy.management.Delete(sample_layer)
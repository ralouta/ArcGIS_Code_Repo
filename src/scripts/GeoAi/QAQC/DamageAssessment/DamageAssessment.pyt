import json
import os
import re
import shutil
import statistics
import urllib.request

import arcpy


TOOL_VERSION = "3.0.0"
SAM3_ITEM_ID = "37ef2e1ba0c042ce99501f56295ec0d4"
EO_DINO_ITEM_ID = "93e8b9ad20734fe7a1641e46385535fc"
WAYBACK_CATALOG_URL = (
    "https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/waybackconfig.json"
)
PORTAL_ITEM_URL = "https://www.arcgis.com/sharing/rest/content/items/{item_id}"
FEATURE_PROFILES = {
    "Buildings": {
        "prompt": "building",
        "detection_cell_size": 0.3,
        "embedding_cell_size": 0.3125,
        "regularize": True,
    },
    "Bridges": {
        "prompt": "bridge",
        "detection_cell_size": 0.3,
        "embedding_cell_size": 0.3125,
        "regularize": False,
    },
    "Roads": {
        "prompt": "road",
        "detection_cell_size": 0.5,
        "embedding_cell_size": 0.5,
        "regularize": False,
    },
    "Debris": {
        "prompt": "debris",
        "detection_cell_size": 0.2,
        "embedding_cell_size": 0.2,
        "regularize": False,
    },
    "Vehicles": {
        "prompt": "vehicle",
        "detection_cell_size": 0.15,
        "embedding_cell_size": 0.15,
        "regularize": False,
    },
    "Utility Poles": {
        "prompt": "utility pole",
        "detection_cell_size": 0.1,
        "embedding_cell_size": 0.1,
        "regularize": False,
    },
    "Custom": {
        "prompt": "",
        "detection_cell_size": 0.3,
        "embedding_cell_size": 0.3125,
        "regularize": False,
    },
}
_WAYBACK_RELEASES = None
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
        self.label = "Damage Assessment"
        self.alias = "damageassessment"
        self.tools = [AutomatedDamageAssessment, ClassifyBuildingDamage]


class AutomatedDamageAssessment(object):
    IN_TARGET = 0
    FEATURE_TYPE = 1
    AOI = 2
    PRE_SOURCE = 3
    PRE_IMAGE = 4
    WAYBACK = 5
    SAM_MODEL = 6
    CUSTOM_PROMPT = 7
    DETECTION_CELL_SIZE = 8
    POST_IMAGE = 9
    SAMPLE_POINTS = 10
    EMBEDDING_MODEL = 11
    MODEL_CACHE = 12
    GPU_ID = 13
    BATCH_SIZE = 14
    EMBEDDING_CELL_SIZE = 15
    GRID_SIZE = 16
    SIMILARITY_THRESHOLD = 17
    OUT_CLASSIFIED = 18
    MODERATE_THRESHOLD = 19
    HIGH_THRESHOLD = 20
    OUT_TARGET = 21
    OUT_EMBEDDINGS = 22
    OUT_SIMILAR = 23

    def __init__(self):
        self.label = "Automated Damage Assessment"
        self.description = (
            "Extracts target features from pre-event imagery when needed, generates "
            "EO-DINO embeddings from post-event imagery, finds areas similar to "
            "user-marked damage examples, and classifies target features by overlap."
        )
        self.canRunInBackground = False
        self._last_feature_type = None

    def getParameterInfo(self):
        in_target = arcpy.Parameter(
            displayName="Input Target Features (Optional)",
            name="in_target_features",
            datatype="GPFeatureLayer",
            parameterType="Optional",
            direction="Input",
        )
        in_target.filter.list = ["Polygon"]
        in_target.category = "1. Target Features"

        feature_type = arcpy.Parameter(
            displayName="Feature Type",
            name="feature_type",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        feature_type.filter.type = "ValueList"
        feature_type.filter.list = list(FEATURE_PROFILES)
        feature_type.value = "Buildings"
        feature_type.category = "1. Target Features"

        aoi = arcpy.Parameter(
            displayName="Area of Interest",
            name="in_aoi",
            datatype="GPFeatureLayer",
            parameterType="Optional",
            direction="Input",
        )
        aoi.filter.list = ["Polygon"]
        aoi.category = "1. Target Features"

        pre_source = arcpy.Parameter(
            displayName="Pre-Event Imagery Source",
            name="pre_event_source",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        pre_source.filter.type = "ValueList"
        pre_source.filter.list = ["Input Imagery", "World Imagery Wayback"]
        pre_source.value = "Input Imagery"
        pre_source.category = "2. Pre-Event Feature Extraction"

        pre_image = arcpy.Parameter(
            displayName="Pre-Event Imagery",
            name="in_pre_event_imagery",
            datatype="GPRasterLayer",
            parameterType="Optional",
            direction="Input",
        )
        pre_image.category = "2. Pre-Event Feature Extraction"

        wayback = arcpy.Parameter(
            displayName="World Imagery Wayback Release",
            name="wayback_release",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        wayback.filter.type = "ValueList"
        wayback.filter.list = [release[0] for release in _get_wayback_releases()]
        wayback.category = "2. Pre-Event Feature Extraction"

        sam_model = arcpy.Parameter(
            displayName="Custom Extraction Model (.dlpk, Optional; Default: Living Atlas SAM3)",
            name="in_sam_model",
            datatype="DEFile",
            parameterType="Optional",
            direction="Input",
        )
        sam_model.filter.list = ["dlpk"]
        sam_model.category = "2. Pre-Event Feature Extraction"

        custom_prompt = arcpy.Parameter(
            displayName="Custom SAM3 Text Prompt",
            name="custom_sam_prompt",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        custom_prompt.category = "2. Pre-Event Feature Extraction"

        detection_cell_size = arcpy.Parameter(
            displayName="Feature Detection Cell Size",
            name="detection_cell_size",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
        )
        detection_cell_size.value = FEATURE_PROFILES["Buildings"]["detection_cell_size"]
        detection_cell_size.category = "2. Pre-Event Feature Extraction"

        post_image = arcpy.Parameter(
            displayName="Post-Event Imagery",
            name="in_post_event_imagery",
            datatype="GPRasterLayer",
            parameterType="Required",
            direction="Input",
        )
        post_image.category = "3. Post-Event Similarity"

        sample_points = arcpy.Parameter(
            displayName="Damage Example Points (6-20)",
            name="in_damage_sample_points",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        sample_points.filter.list = ["Point", "Multipoint"]
        sample_points.category = "3. Post-Event Similarity"

        embedding_model = arcpy.Parameter(
            displayName="Custom Embedding Model (.dlpk, Optional; Default: Living Atlas EO-DINO)",
            name="in_embedding_model",
            datatype="DEFile",
            parameterType="Optional",
            direction="Input",
        )
        embedding_model.filter.list = ["dlpk"]
        embedding_model.category = "3. Post-Event Similarity"

        model_cache = arcpy.Parameter(
            displayName="Downloaded Model Cache",
            name="model_cache",
            datatype="DEFolder",
            parameterType="Optional",
            direction="Input",
        )
        model_cache.value = os.path.join(
            os.path.expanduser("~"), "Documents", "ArcGIS", "Packages", "DamageAssessment"
        )
        model_cache.category = "3. Post-Event Similarity"

        gpu_id = arcpy.Parameter(
            displayName="GPU ID",
            name="gpu_id",
            datatype="GPLong",
            parameterType="Optional",
            direction="Input",
        )
        gpu_id.value = 0
        gpu_id.category = "3. Post-Event Similarity"

        batch_size = arcpy.Parameter(
            displayName="Batch Size",
            name="batch_size",
            datatype="GPLong",
            parameterType="Optional",
            direction="Input",
        )
        batch_size.value = 16
        batch_size.category = "3. Post-Event Similarity"

        embedding_cell_size = arcpy.Parameter(
            displayName="Embedding Cell Size",
            name="embedding_cell_size",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
        )
        embedding_cell_size.value = FEATURE_PROFILES["Buildings"]["embedding_cell_size"]
        embedding_cell_size.category = "3. Post-Event Similarity"

        grid_size = arcpy.Parameter(
            displayName="Embedding Grid Size (0 = Auto)",
            name="grid_size",
            datatype="GPLong",
            parameterType="Optional",
            direction="Input",
        )
        grid_size.value = 0
        grid_size.category = "3. Post-Event Similarity"

        similarity_threshold = arcpy.Parameter(
            displayName="Similarity Threshold",
            name="similarity_threshold",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
        )
        similarity_threshold.value = 0.55
        similarity_threshold.category = "3. Post-Event Similarity"

        out_classified = arcpy.Parameter(
            displayName="Output Classified Target Features",
            name="out_classified_features",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Output",
        )
        out_classified.category = "4. Outputs and Classification"

        moderate_threshold = arcpy.Parameter(
            displayName="Moderate Damage Minimum Coverage (%)",
            name="moderate_coverage_threshold",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
        )
        moderate_threshold.value = 20.0
        moderate_threshold.category = "4. Outputs and Classification"

        high_threshold = arcpy.Parameter(
            displayName="High Damage Minimum Coverage (%)",
            name="high_coverage_threshold",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
        )
        high_threshold.value = 50.0
        high_threshold.category = "4. Outputs and Classification"

        out_target = arcpy.Parameter(
            displayName="Target Features Used",
            name="out_target_features",
            datatype="DEFeatureClass",
            parameterType="Derived",
            direction="Output",
        )
        out_target.category = "4. Outputs and Classification"

        out_embeddings = arcpy.Parameter(
            displayName="Post-Event Embeddings",
            name="out_embeddings",
            datatype="DEFeatureClass",
            parameterType="Derived",
            direction="Output",
        )
        out_embeddings.category = "4. Outputs and Classification"

        out_similar = arcpy.Parameter(
            displayName="Similar Embedding Features",
            name="out_similar_embeddings",
            datatype="DEFeatureClass",
            parameterType="Derived",
            direction="Output",
        )
        out_similar.category = "4. Outputs and Classification"

        return [
            in_target,
            feature_type,
            aoi,
            pre_source,
            pre_image,
            wayback,
            sam_model,
            custom_prompt,
            detection_cell_size,
            post_image,
            sample_points,
            embedding_model,
            model_cache,
            gpu_id,
            batch_size,
            embedding_cell_size,
            grid_size,
            similarity_threshold,
            out_classified,
            moderate_threshold,
            high_threshold,
            out_target,
            out_embeddings,
            out_similar,
        ]

    def updateParameters(self, parameters):
        has_target_features = bool(parameters[self.IN_TARGET].valueAsText)
        for index in (
            self.AOI,
            self.PRE_SOURCE,
            self.PRE_IMAGE,
            self.WAYBACK,
            self.SAM_MODEL,
            self.CUSTOM_PROMPT,
            self.DETECTION_CELL_SIZE,
        ):
            parameters[index].enabled = not has_target_features

        pre_source = parameters[self.PRE_SOURCE].valueAsText or "Input Imagery"
        if not has_target_features:
            parameters[self.PRE_IMAGE].enabled = pre_source == "Input Imagery"
            parameters[self.WAYBACK].enabled = pre_source == "World Imagery Wayback"

        feature_type = parameters[self.FEATURE_TYPE].valueAsText or "Buildings"
        parameters[self.CUSTOM_PROMPT].enabled = (
            not has_target_features and feature_type == "Custom"
        )
        if feature_type != self._last_feature_type:
            profile = FEATURE_PROFILES[feature_type]
            parameters[self.DETECTION_CELL_SIZE].value = profile["detection_cell_size"]
            parameters[self.EMBEDDING_CELL_SIZE].value = profile["embedding_cell_size"]
            self._last_feature_type = feature_type
        return

    def updateMessages(self, parameters):
        has_target_features = bool(parameters[self.IN_TARGET].valueAsText)
        if not has_target_features:
            if not parameters[self.AOI].valueAsText:
                parameters[self.AOI].setErrorMessage(
                    "An area of interest is required when target features are not supplied."
                )
            pre_source = parameters[self.PRE_SOURCE].valueAsText
            if pre_source == "Input Imagery" and not parameters[self.PRE_IMAGE].valueAsText:
                parameters[self.PRE_IMAGE].setErrorMessage(
                    "Provide pre-event imagery or choose World Imagery Wayback."
                )
            if pre_source == "World Imagery Wayback" and not parameters[self.WAYBACK].valueAsText:
                parameters[self.WAYBACK].setErrorMessage("Choose a Wayback release.")
            if (
                parameters[self.FEATURE_TYPE].valueAsText == "Custom"
                and not parameters[self.CUSTOM_PROMPT].valueAsText
            ):
                parameters[self.CUSTOM_PROMPT].setErrorMessage(
                    "Enter the object concept that SAM3 should segment."
                )

        if not has_target_features:
            _set_positive_error(
                parameters[self.DETECTION_CELL_SIZE], "Detection cell size"
            )
        _set_positive_error(parameters[self.EMBEDDING_CELL_SIZE], "Embedding cell size")

        grid_size = parameters[self.GRID_SIZE].value
        if grid_size is not None and int(grid_size) < 0:
            parameters[self.GRID_SIZE].setErrorMessage("Grid size must be 0 (Auto) or greater.")

        similarity = parameters[self.SIMILARITY_THRESHOLD].value
        if similarity is not None and not 0 < float(similarity) <= 1:
            parameters[self.SIMILARITY_THRESHOLD].setErrorMessage(
                "Similarity threshold must be greater than 0 and at most 1."
            )

        batch_size = parameters[self.BATCH_SIZE].value
        if batch_size is not None and int(batch_size) < 1:
            parameters[self.BATCH_SIZE].setErrorMessage("Batch size must be at least 1.")

        _validate_coverage_parameters(
            parameters[self.MODERATE_THRESHOLD], parameters[self.HIGH_THRESHOLD]
        )
        output_path = parameters[self.OUT_CLASSIFIED].valueAsText
        if output_path and not _geodatabase_workspace(output_path):
            parameters[self.OUT_CLASSIFIED].setErrorMessage(
                "Output must be stored in a file or enterprise geodatabase because "
                "embedding feature classes contain a BLOB field."
            )
        return

    def execute(self, parameters, messages):
        in_target = parameters[self.IN_TARGET].valueAsText
        feature_type = parameters[self.FEATURE_TYPE].valueAsText
        aoi = parameters[self.AOI].valueAsText
        pre_source = parameters[self.PRE_SOURCE].valueAsText or "Input Imagery"
        pre_image = parameters[self.PRE_IMAGE].valueAsText
        wayback_release = parameters[self.WAYBACK].valueAsText
        sam_model = parameters[self.SAM_MODEL].valueAsText
        custom_prompt = parameters[self.CUSTOM_PROMPT].valueAsText
        post_image = parameters[self.POST_IMAGE].valueAsText
        sample_points = parameters[self.SAMPLE_POINTS].valueAsText
        embedding_model = parameters[self.EMBEDDING_MODEL].valueAsText
        model_cache = parameters[self.MODEL_CACHE].valueAsText
        gpu_id = int(parameters[self.GPU_ID].value or 0)
        batch_size = int(parameters[self.BATCH_SIZE].value or 16)
        embedding_cell_size = float(parameters[self.EMBEDDING_CELL_SIZE].value or 0.3125)
        requested_grid_size = int(parameters[self.GRID_SIZE].value or 0)
        similarity_threshold = float(parameters[self.SIMILARITY_THRESHOLD].value or 0.55)
        out_classified = parameters[self.OUT_CLASSIFIED].valueAsText
        moderate_threshold = float(parameters[self.MODERATE_THRESHOLD].value or 20.0)
        high_threshold = float(parameters[self.HIGH_THRESHOLD].value or 50.0)

        output_workspace = _geodatabase_workspace(out_classified)
        if not output_workspace:
            raise arcpy.ExecuteError(
                "Output Classified Target Features must be stored in a file or "
                "enterprise geodatabase."
            )
        scratch_workspace = arcpy.env.scratchGDB
        messages.addMessage(f"Automated Damage Assessment version {TOOL_VERSION}")

        target_features = in_target
        if target_features:
            messages.addMessage("Using user-supplied target features; pre-event extraction is skipped.")
        else:
            detection_cell_size = float(
                parameters[self.DETECTION_CELL_SIZE].value
                or FEATURE_PROFILES[feature_type]["detection_cell_size"]
            )
            source_imagery = pre_image
            if pre_source == "World Imagery Wayback":
                source_imagery = _resolve_wayback_imagery(wayback_release, messages)

            sam_model = _resolve_model(
                sam_model,
                SAM3_ITEM_ID,
                "SAM3.dlpk",
                model_cache,
                messages,
            )
            prompt = custom_prompt or FEATURE_PROFILES[feature_type]["prompt"]
            target_features = _extract_target_features(
                source_imagery,
                aoi,
                feature_type,
                prompt,
                sam_model,
                detection_cell_size,
                batch_size,
                gpu_id,
                output_workspace,
                scratch_workspace,
                messages,
            )

        parameters[self.OUT_TARGET].value = target_features
        query_features = _select_damage_queries(
            target_features, sample_points, scratch_workspace, messages
        )

        try:
            grid_size = requested_grid_size or _recommend_grid_size(
                target_features, embedding_cell_size
            )
            messages.addMessage(f"Embedding grid size: {grid_size}")
            embedding_model = _resolve_model(
                embedding_model,
                EO_DINO_ITEM_ID,
                "EO-DINO.dlpk",
                model_cache,
                messages,
            )

            out_embeddings = arcpy.CreateUniqueName(
                "Damage_PostEvent_Embeddings", output_workspace
            )
            output_spatial_reference = arcpy.Describe(target_features).spatialReference
            embedding_cell_size_units = _meters_to_spatial_units(
                embedding_cell_size, output_spatial_reference
            )
            messages.addMessage("Generating embeddings from post-event imagery...")
            with arcpy.EnvManager(
                gpuId=gpu_id,
                extent=arcpy.Describe(target_features).extent,
                cellSize=embedding_cell_size_units,
                processorType="GPU",
                outputCoordinateSystem=output_spatial_reference,
            ):
                arcpy.geoai.GenerateEmbeddingsUsingAIModels(
                    in_data=post_image,
                    out_embeddings_feature_class=out_embeddings,
                    in_model_definition_file=embedding_model,
                    arguments=(
                        f"batch_size {batch_size};data_src RGB;"
                        "radiometric_offset_correction False;"
                        f"grid_size {grid_size}"
                    ),
                )
            parameters[self.OUT_EMBEDDINGS].value = out_embeddings

            out_similar = arcpy.CreateUniqueName(
                "Damage_Similar_Embeddings", output_workspace
            )
            messages.addMessage("Finding post-event embeddings similar to the damage examples...")
            arcpy.geoai.FindSimilarFeaturesUsingEmbeddings(
                embedding_features=out_embeddings,
                query_features=query_features,
                out_embeddings_feature_class=out_similar,
                threshold=similarity_threshold,
            )
            parameters[self.OUT_SIMILAR].value = out_similar

            _run_damage_classification(
                target_features,
                out_similar,
                out_classified,
                moderate_threshold,
                high_threshold,
                "INTERSECT",
                None,
                messages,
            )
            parameters[self.OUT_CLASSIFIED].value = out_classified
        finally:
            if arcpy.Exists(query_features):
                arcpy.management.Delete(query_features)


def _set_positive_error(parameter, label):
    if parameter.value is not None and float(parameter.value) <= 0:
        parameter.setErrorMessage(f"{label} must be greater than 0.")


def _geodatabase_workspace(dataset_path):
    match = re.search(r"(?i)^(.+?\.(?:gdb|sde))(?:[\\/].*)?$", dataset_path or "")
    return match.group(1) if match else None


def _meters_to_spatial_units(distance_meters, spatial_reference):
    if not spatial_reference or spatial_reference.type != "Projected":
        raise arcpy.ExecuteError(
            "Target features and the area of interest must use a projected coordinate "
            "system so meter-based cell sizes and footprint tolerances are meaningful."
        )
    meters_per_unit = spatial_reference.metersPerUnit
    if not meters_per_unit or meters_per_unit <= 0:
        raise arcpy.ExecuteError(
            "The target coordinate system does not define a valid linear unit."
        )
    return distance_meters / meters_per_unit


def _validate_coverage_parameters(moderate_parameter, high_parameter):
    moderate_threshold = (
        float(moderate_parameter.value) if moderate_parameter.value is not None else None
    )
    high_threshold = float(high_parameter.value) if high_parameter.value is not None else None
    if moderate_threshold is not None and not 0 < moderate_threshold < 100:
        moderate_parameter.setErrorMessage(
            "Moderate coverage must be greater than 0 and less than 100."
        )
    if high_threshold is not None and not 0 < high_threshold <= 100:
        high_parameter.setErrorMessage(
            "High coverage must be greater than 0 and at most 100."
        )
    if (
        moderate_threshold is not None
        and high_threshold is not None
        and moderate_threshold >= high_threshold
    ):
        high_parameter.setErrorMessage("High coverage must be greater than moderate coverage.")


def _request_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "ArcGIS-Damage-Assessment"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def _get_wayback_releases():
    global _WAYBACK_RELEASES
    if _WAYBACK_RELEASES is not None:
        return _WAYBACK_RELEASES

    try:
        catalog = _request_json(WAYBACK_CATALOG_URL)
        releases = []
        for entry in catalog.values():
            title = entry.get("itemTitle")
            item_id = entry.get("itemID")
            date_match = re.search(r"(\d{4}-\d{2}-\d{2})", title or "")
            if title and item_id and date_match:
                releases.append((title, item_id, date_match.group(1)))
        _WAYBACK_RELEASES = sorted(releases, key=lambda item: item[2], reverse=True)
    except Exception:
        _WAYBACK_RELEASES = []
    return _WAYBACK_RELEASES


def _resolve_wayback_imagery(release_title, messages):
    release = next(
        (item for item in _get_wayback_releases() if item[0] == release_title), None
    )
    if release is None:
        raise arcpy.ExecuteError(
            "The selected Wayback release could not be resolved. Refresh the toolbox "
            "while connected to the internet or provide pre-event imagery."
        )

    try:
        active_map = arcpy.mp.ArcGISProject("CURRENT").activeMap
        if active_map is None:
            raise RuntimeError("No active map is available.")
        for layer in active_map.listLayers():
            if layer.name == release_title:
                messages.addMessage(f"Using map layer: {release_title}")
                return layer

        item_path = f"https://www.arcgis.com/home/item.html?id={release[1]}"
        messages.addMessage(f"Adding Wayback release to the active map: {release_title}")
        added_layer = active_map.addDataFromPath(item_path)
        if added_layer is None:
            raise RuntimeError("ArcGIS Pro did not return the added layer.")
        return added_layer
    except Exception as error:
        raise arcpy.ExecuteError(
            f"Could not add {release_title} to the active map. Add that Living Atlas "
            f"Wayback layer to the map and run the tool again. Details: {error}"
        )


def _resolve_model(local_path, item_id, file_name, cache_folder, messages):
    if local_path:
        messages.addMessage(f"Using custom model: {local_path}")
        return local_path
    if not cache_folder:
        raise arcpy.ExecuteError("Choose a model cache folder or provide local model files.")

    os.makedirs(cache_folder, exist_ok=True)
    model_path = os.path.join(cache_folder, file_name)
    if os.path.isfile(model_path) and os.path.getsize(model_path) > 0:
        messages.addMessage(
            f"Using default Living Atlas model {item_id} from cache: {model_path}"
        )
        return model_path

    partial_path = model_path + ".part"
    download_url = PORTAL_ITEM_URL.format(item_id=item_id) + "/data"
    messages.addMessage(
        f"Downloading default Living Atlas model {item_id} ({file_name}). "
        "This one-time download may take several minutes..."
    )
    try:
        request = urllib.request.Request(
            download_url, headers={"User-Agent": "ArcGIS-Damage-Assessment"}
        )
        with urllib.request.urlopen(request, timeout=120) as response, open(
            partial_path, "wb"
        ) as output_file:
            shutil.copyfileobj(response, output_file, length=1024 * 1024)
        os.replace(partial_path, model_path)
    except Exception as error:
        if os.path.exists(partial_path):
            os.remove(partial_path)
        raise arcpy.ExecuteError(f"Could not download {file_name}: {error}")
    return model_path


def _extract_target_features(
    source_imagery,
    aoi,
    feature_type,
    prompt,
    sam_model,
    cell_size,
    batch_size,
    gpu_id,
    output_workspace,
    scratch_workspace,
    messages,
):
    raw_features = arcpy.CreateUniqueName("sam3_raw", scratch_workspace)
    nms_features = arcpy.CreateUniqueName("sam3_nms", scratch_workspace)
    safe_feature_type = re.sub("[^A-Za-z0-9_]+", "_", feature_type)
    target_features = arcpy.CreateUniqueName(
        f"Damage_{safe_feature_type}", output_workspace
    )
    spatial_reference = arcpy.Describe(aoi).spatialReference
    cell_size_units = _meters_to_spatial_units(cell_size, spatial_reference)

    try:
        messages.addMessage(f"Detecting {feature_type.lower()} with SAM3...")
        with arcpy.EnvManager(
            gpuId=gpu_id,
            extent=arcpy.Describe(aoi).extent,
            cellSize=cell_size_units,
            processorType="GPU",
            outputCoordinateSystem=spatial_reference,
        ):
            arcpy.ia.DetectObjectsUsingDeepLearning(
                in_raster=source_imagery,
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

        messages.addMessage("Applying nonmaximum suppression to extracted features...")
        arcpy.ia.NonMaximumSuppression(
            in_featureclass=raw_features,
            confidence_score_field="Confidence",
            out_featureclass=nms_features,
            class_value_field="Class",
            max_overlap_ratio=0.1,
        )

        if FEATURE_PROFILES[feature_type]["regularize"]:
            messages.addMessage("Regularizing building footprints...")
            tolerance_units = _meters_to_spatial_units(10.0, spatial_reference)
            densification_units = _meters_to_spatial_units(1.0, spatial_reference)
            precision_units = _meters_to_spatial_units(0.25, spatial_reference)
            min_radius_units = _meters_to_spatial_units(0.1, spatial_reference)
            max_radius_units = _meters_to_spatial_units(1000000.0, spatial_reference)
            arcpy.ddd.RegularizeBuildingFootprint(
                in_features=nms_features,
                out_feature_class=target_features,
                method="RIGHT_ANGLES",
                tolerance=tolerance_units,
                densification=densification_units,
                precision=precision_units,
                diagonal_penalty=1.5,
                min_radius=min_radius_units,
                max_radius=max_radius_units,
                alignment_feature=None,
                alignment_tolerance=None,
                tolerance_type="DISTANCE",
            )
        else:
            arcpy.management.CopyFeatures(nms_features, target_features)
    finally:
        for dataset in (raw_features, nms_features):
            if arcpy.Exists(dataset):
                arcpy.management.Delete(dataset)

    if int(arcpy.management.GetCount(target_features)[0]) == 0:
        raise arcpy.ExecuteError(
            f"SAM3 did not extract any {feature_type.lower()} in the area of interest."
        )
    return target_features


def _select_damage_queries(target_features, sample_points, scratch_workspace, messages):
    target_layer = arcpy.CreateUniqueName("damage_target_selection")
    query_features = arcpy.CreateUniqueName("damage_queries", scratch_workspace)
    try:
        arcpy.management.MakeFeatureLayer(target_features, target_layer)
        arcpy.management.SelectLayerByLocation(
            target_layer, "INTERSECT", sample_points, None, "NEW_SELECTION"
        )
        selected_count = int(arcpy.management.GetCount(target_layer)[0])
        if not 6 <= selected_count <= 20:
            raise arcpy.ExecuteError(
                "Damage example points must intersect 6-20 unique target features; "
                f"{selected_count} unique feature(s) were selected."
            )
        arcpy.management.CopyFeatures(target_layer, query_features)
        messages.addMessage(
            f"Using {selected_count} target features as post-event damage examples."
        )
    finally:
        if arcpy.Exists(target_layer):
            arcpy.management.Delete(target_layer)
    return query_features


def _recommend_grid_size(target_features, cell_size):
    spatial_reference = arcpy.Describe(target_features).spatialReference
    meters_per_unit = spatial_reference.metersPerUnit
    _meters_to_spatial_units(cell_size, spatial_reference)
    widths = []
    with arcpy.da.SearchCursor(target_features, ["SHAPE@"]) as cursor:
        for index, (geometry,) in enumerate(cursor):
            if geometry and not geometry.isEmpty:
                extent = geometry.extent
                width = min(extent.width, extent.height) * meters_per_unit
                if width > 0:
                    widths.append(width)
            if index >= 4999:
                break

    if not widths:
        return 5
    median_width = statistics.median(widths)
    estimated_size = int(round((1.5 * median_width) / (16.0 * cell_size)))
    estimated_size = max(3, min(11, estimated_size))
    if estimated_size % 2 == 0:
        estimated_size += 1 if estimated_size < 11 else -1
    return estimated_size


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
        _validate_coverage_parameters(parameters[3], parameters[4])

        if parameters[5].valueAsText != "INTERSECT":
            parameters[5].setErrorMessage("Coverage classification requires INTERSECT.")
        return

    def execute(self, parameters, messages):
        buildings = parameters[0].valueAsText
        similar_features = parameters[1].valueAsText
        output_features = parameters[2].valueAsText
        moderate_coverage_threshold = float(parameters[3].value or 20.0)
        high_coverage_threshold = float(parameters[4].value or 50.0)
        match_option = parameters[5].valueAsText
        search_radius = parameters[6].valueAsText or None

        _run_damage_classification(
            buildings,
            similar_features,
            output_features,
            moderate_coverage_threshold,
            high_coverage_threshold,
            match_option,
            search_radius,
            messages,
        )
        parameters[2].value = output_features


def _run_damage_classification(
    target_features,
    similar_features,
    output_features,
    moderate_coverage_threshold,
    high_coverage_threshold,
    match_option,
    search_radius,
    messages,
):
    messages.addMessage(f"Damage Assessment classifier version {TOOL_VERSION}")
    messages.addMessage("Counting similar-embedding features for each target feature...")
    field_mappings = _build_field_mappings(target_features)
    arcpy.analysis.SpatialJoin(
        target_features=target_features,
        join_features=similar_features,
        out_feature_class=output_features,
        join_operation="JOIN_ONE_TO_ONE",
        join_type="KEEP_ALL",
        field_mapping=field_mappings,
        match_option=match_option,
        search_radius=search_radius,
    )
    count_before_repair = int(arcpy.management.GetCount(output_features)[0])
    messages.addMessage("Repairing output target geometries...")
    arcpy.management.RepairGeometry(output_features, "DELETE_NULL", "ESRI")
    count_after_repair = int(arcpy.management.GetCount(output_features)[0])
    removed_by_repair = count_before_repair - count_after_repair
    if removed_by_repair:
        messages.addWarningMessage(
            f"Repair Geometry removed {removed_by_repair} feature(s) with null geometry."
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
        object_id_preview = ", ".join(str(object_id) for object_id in invalid_area_oids[:20])
        if len(invalid_area_oids) > 20:
            object_id_preview += ", ..."
        messages.addWarningMessage(
            "Excluded {0} feature(s) with empty or zero-area geometry. "
            "Output object IDs before deletion: {1}".format(
                len(invalid_area_oids), object_id_preview
            )
        )

    messages.addMessage("Calculating embedding coverage within each target feature...")
    overlap_areas = _calculate_overlap_areas(output_features, similar_features, messages)

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
        messages.addMessage(f"{damage_class}: {class_totals[damage_class]} features")

    messages.addWarningMessage(
        "These classes indicate relative image evidence, not confirmed structural damage. "
        "No Matching Damage Evidence may also mean the feature is outside the embedding analysis extent. "
        "Validate Moderate and High Damage Evidence against post-event imagery or field observations."
    )


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
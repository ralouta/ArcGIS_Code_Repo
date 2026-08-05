import json
import os
import re
import shutil
import statistics
import urllib.request

import arcpy


TOOL_VERSION = "4.2.1"
WEB_MERCATOR_WKIDS = {3857, 102100}
SAM3_ITEM_ID = "37ef2e1ba0c042ce99501f56295ec0d4"
EO_DINO_ITEM_ID = "93e8b9ad20734fe7a1641e46385535fc"
WAYBACK_CATALOG_URL = (
    "https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/waybackconfig.json"
)
PORTAL_ITEM_URL = "https://www.arcgis.com/sharing/rest/content/items/{item_id}"
DEFAULT_MODEL_CACHE = os.path.join(
    os.path.expanduser("~"), "Documents", "ArcGIS", "Packages", "DamageAssessment"
)
FEATURE_PROFILES = {
    "Buildings": {
        "prompt": "building",
        "detection_cell_size": 0.3,
        "regularize": True,
    },
    "Bridges": {
        "prompt": "bridge",
        "detection_cell_size": 0.3,
        "regularize": False,
    },
    "Roads": {
        "prompt": "road",
        "detection_cell_size": 0.5,
        "regularize": False,
    },
    "Debris": {
        "prompt": "debris",
        "detection_cell_size": 0.2,
        "regularize": False,
    },
    "Vehicles": {
        "prompt": "vehicle",
        "detection_cell_size": 0.15,
        "regularize": False,
    },
    "Trees": {
        "prompt": "tree",
        "detection_cell_size": 0.2,
        "regularize": False,
    },
    "Utility Poles": {
        "prompt": "utility pole",
        "detection_cell_size": 0.1,
        "regularize": False,
    },
    "Custom": {
        "prompt": "",
        "detection_cell_size": 0.3,
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
        self.alias = "automateddamageassessment"
        self.tools = [AutomatedDamageAssessment]


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
    GPU_ID = 12
    BATCH_SIZE = 13
    GRID_SIZE = 14
    SIMILARITY_THRESHOLD = 15
    OUT_CLASSIFIED = 16
    MODERATE_THRESHOLD = 17
    HIGH_THRESHOLD = 18
    OUT_TARGET = 19
    OUT_EMBEDDINGS = 20
    OUT_SIMILAR = 21
    KEEP_INTERMEDIATE = 22

    def __init__(self):
        self.label = "Automated Damage Assessment"
        self.description = (
            "Extracts target features from pre-event imagery when needed, generates "
            "EO-DINO embeddings from post-event imagery, finds areas similar to "
            "user-marked damage examples, and classifies target features by overlap."
        )
        self.canRunInBackground = False
        self.environments = ["extent"]
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
            displayName="Area of Interest Polygon (Optional; Overrides Extent Environment)",
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
            displayName="Pre-Event Imagery Layer (from Active Map)",
            name="in_pre_event_imagery",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        pre_image.filter.type = "ValueList"
        pre_image.filter.list = _get_active_map_raster_layer_names()
        pre_image.category = "2. Pre-Event Feature Extraction"

        wayback = arcpy.Parameter(
            displayName="World Imagery Wayback Archive Release",
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
            displayName="Post-Event Imagery Layer (from Active Map)",
            name="in_post_event_imagery",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        post_image.filter.type = "ValueList"
        post_image.filter.list = _get_active_map_raster_layer_names()
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

        grid_size = arcpy.Parameter(
            displayName="Embedding Grid Size (Optional; Blank = Auto)",
            name="grid_size",
            datatype="GPLong",
            parameterType="Optional",
            direction="Input",
        )
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

        keep_intermediate = arcpy.Parameter(
            displayName="Keep Intermediate Data",
            name="keep_intermediate_data",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
        )
        keep_intermediate.value = True
        keep_intermediate.category = "4. Outputs and Classification"

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
            gpu_id,
            batch_size,
            grid_size,
            similarity_threshold,
            out_classified,
            moderate_threshold,
            high_threshold,
            out_target,
            out_embeddings,
            out_similar,
            keep_intermediate,
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

        raster_layer_names = _get_active_map_raster_layer_names()
        parameters[self.PRE_IMAGE].filter.list = raster_layer_names
        parameters[self.POST_IMAGE].filter.list = raster_layer_names

        feature_type = parameters[self.FEATURE_TYPE].valueAsText or "Buildings"
        parameters[self.CUSTOM_PROMPT].enabled = (
            not has_target_features and feature_type == "Custom"
        )
        if feature_type != self._last_feature_type:
            profile = FEATURE_PROFILES[feature_type]
            parameters[self.DETECTION_CELL_SIZE].value = profile["detection_cell_size"]
            self._last_feature_type = feature_type
        return

    def updateMessages(self, parameters):
        has_target_features = bool(parameters[self.IN_TARGET].valueAsText)
        if not has_target_features:
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
        grid_size = parameters[self.GRID_SIZE].value
        if grid_size is not None and int(grid_size) < 1:
            parameters[self.GRID_SIZE].setErrorMessage(
                "Grid size must be a positive integer or left blank for Auto."
            )

        similarity = parameters[self.SIMILARITY_THRESHOLD].value
        if similarity is not None and not 0 < float(similarity) <= 1:
            parameters[self.SIMILARITY_THRESHOLD].setErrorMessage(
                "Similarity threshold must be greater than 0 and at most 1."
            )

        batch_size = parameters[self.BATCH_SIZE].value
        if batch_size is not None and int(batch_size) < 1:
            parameters[self.BATCH_SIZE].setErrorMessage("Batch size must be at least 1.")

        sample_points = parameters[self.SAMPLE_POINTS].valueAsText
        if sample_points:
            try:
                sample_count = int(arcpy.management.GetCount(sample_points)[0])
            except Exception:
                sample_count = None
            if sample_count is not None and not 6 <= sample_count <= 20:
                parameters[self.SAMPLE_POINTS].setErrorMessage(
                    "Provide 6-20 damage example point features; "
                    f"the selected layer contains {sample_count}."
                )

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
        pre_image = _resolve_active_map_raster_layer(parameters[self.PRE_IMAGE].valueAsText)
        wayback_release = parameters[self.WAYBACK].valueAsText
        sam_model = parameters[self.SAM_MODEL].valueAsText
        custom_prompt = parameters[self.CUSTOM_PROMPT].valueAsText
        post_image = _resolve_active_map_raster_layer(parameters[self.POST_IMAGE].valueAsText)
        sample_points = parameters[self.SAMPLE_POINTS].valueAsText
        embedding_model = parameters[self.EMBEDDING_MODEL].valueAsText
        gpu_id = int(parameters[self.GPU_ID].value or 0)
        batch_size = int(parameters[self.BATCH_SIZE].value or 16)
        requested_grid_size = (
            int(parameters[self.GRID_SIZE].value)
            if parameters[self.GRID_SIZE].value is not None
            else None
        )
        similarity_threshold = float(parameters[self.SIMILARITY_THRESHOLD].value or 0.55)
        out_classified = parameters[self.OUT_CLASSIFIED].valueAsText
        moderate_threshold = float(parameters[self.MODERATE_THRESHOLD].value or 20.0)
        high_threshold = float(parameters[self.HIGH_THRESHOLD].value or 50.0)
        keep_intermediate = parameters[self.KEEP_INTERMEDIATE].value is not False

        output_workspace = _geodatabase_workspace(out_classified)
        if not output_workspace:
            raise arcpy.ExecuteError(
                "Output Classified Target Features must be stored in a file or "
                "enterprise geodatabase."
            )
        scratch_workspace = arcpy.env.scratchGDB
        messages.addMessage(f"Automated Damage Assessment version {TOOL_VERSION}")
        messages.addMessage(f"Feature type: {feature_type}")
        post_image = _ensure_web_mercator_raster(
            post_image, "Post-event imagery", messages
        )

        target_features = in_target
        generated_target_features = None
        out_embeddings = None
        out_similar = None
        if target_features:
            messages.addMessage("Using user-supplied target features; pre-event extraction is skipped.")
            analysis_extent, analysis_spatial_reference, extent_source = (
                _resolve_analysis_extent(None, target_features, False)
            )
        else:
            detection_cell_size = float(
                parameters[self.DETECTION_CELL_SIZE].value
                or FEATURE_PROFILES[feature_type]["detection_cell_size"]
            )
            source_imagery = pre_image
            if pre_source == "World Imagery Wayback":
                source_imagery = _resolve_wayback_imagery(wayback_release, messages)
            source_imagery = _ensure_web_mercator_raster(
                source_imagery,
                "Pre-event imagery",
                messages,
                assume_web_mercator=pre_source == "World Imagery Wayback",
            )

            analysis_extent, analysis_spatial_reference, extent_source = (
                _resolve_analysis_extent(aoi, source_imagery, True)
            )

            sam_model = _resolve_model(
                sam_model,
                SAM3_ITEM_ID,
                "SAM3.dlpk",
                messages,
            )
            prompt = custom_prompt or FEATURE_PROFILES[feature_type]["prompt"]
            target_features = _extract_target_features(
                source_imagery,
                analysis_extent,
                analysis_spatial_reference,
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
            generated_target_features = target_features

        messages.addMessage(f"Analysis extent source: {extent_source}")
        parameters[self.OUT_TARGET].value = target_features
        query_features = _select_damage_queries(
            target_features,
            sample_points,
            feature_type,
            scratch_workspace,
            messages,
        )

        try:
            grid_size = requested_grid_size or _recommend_grid_size(
                target_features, post_image
            )
            grid_source = "user supplied" if requested_grid_size else "Auto recommendation"
            messages.addMessage(f"Embedding grid size: {grid_size} ({grid_source})")
            embedding_model = _resolve_model(
                embedding_model,
                EO_DINO_ITEM_ID,
                "EO-DINO.dlpk",
                messages,
            )

            out_embeddings = arcpy.CreateUniqueName(
                "Damage_PostEvent_Embeddings", output_workspace
            )
            output_spatial_reference = arcpy.Describe(target_features).spatialReference
            messages.addMessage("Generating embeddings from post-event imagery...")
            with arcpy.EnvManager(
                gpuId=gpu_id,
                extent=analysis_extent,
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
            if not keep_intermediate:
                messages.addMessage("Deleting generated intermediate data...")
                for dataset in (
                    out_similar,
                    out_embeddings,
                    generated_target_features,
                ):
                    if dataset and arcpy.Exists(dataset):
                        arcpy.management.Delete(dataset)
                parameters[self.OUT_TARGET].value = None
                parameters[self.OUT_EMBEDDINGS].value = None
                parameters[self.OUT_SIMILAR].value = None


def _set_positive_error(parameter, label):
    if parameter.value is not None and float(parameter.value) <= 0:
        parameter.setErrorMessage(f"{label} must be greater than 0.")


def _get_environment_extent():
    environment_extent = arcpy.env.extent
    if environment_extent is None or str(environment_extent).strip().lower() in (
        "",
        "none",
    ):
        return None
    return environment_extent


def _resolve_analysis_extent(aoi, fallback_dataset, require_explicit_extent):
    if aoi:
        description = arcpy.Describe(aoi)
        return description.extent, description.spatialReference, "Area of Interest polygon"

    environment_extent = _get_environment_extent()
    if environment_extent:
        spatial_reference = getattr(environment_extent, "spatialReference", None)
        if not spatial_reference or getattr(spatial_reference, "name", "Unknown") == "Unknown":
            spatial_reference = arcpy.Describe(fallback_dataset).spatialReference
        return environment_extent, spatial_reference, "Extent environment"

    if require_explicit_extent:
        raise arcpy.ExecuteError(
            "Provide an Area of Interest polygon or set the Extent environment."
        )

    description = arcpy.Describe(fallback_dataset)
    return description.extent, description.spatialReference, "input target features"


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


def _get_active_map_raster_layers():
    try:
        active_map = arcpy.mp.ArcGISProject("CURRENT").activeMap
    except Exception:
        active_map = None
    if active_map is None:
        return []
    return [
        layer
        for layer in active_map.listLayers()
        if getattr(layer, "isRasterLayer", False)
    ]


def _get_active_map_raster_layer_names():
    return [
        getattr(layer, "longName", layer.name)
        for layer in _get_active_map_raster_layers()
    ]


def _resolve_active_map_raster_layer(layer_name):
    if not layer_name:
        return None
    for layer in _get_active_map_raster_layers():
        if layer_name in (layer.name, getattr(layer, "longName", layer.name)):
            return layer
    raise arcpy.ExecuteError(
        f"Raster layer '{layer_name}' is no longer available in the active map. "
        "Refresh the tool and choose a layer from the dropdown."
    )


def _ensure_web_mercator_raster(
    raster, label, messages, assume_web_mercator=False
):
    if assume_web_mercator:
        return raster

    spatial_reference = getattr(arcpy.Describe(raster), "spatialReference", None)
    wkid = (
        getattr(spatial_reference, "factoryCode", 0)
        or getattr(spatial_reference, "latestWkid", 0)
        or 0
    )
    if wkid in WEB_MERCATOR_WKIDS:
        return raster
    if not spatial_reference or getattr(spatial_reference, "name", "Unknown") == "Unknown":
        raise arcpy.ExecuteError(
            f"{label} must have a defined coordinate system before it can be reprojected."
        )

    messages.addMessage(
        f"Applying the Reproject raster function to {label.lower()}: "
        f"{spatial_reference.name} -> WGS 1984 Web Mercator (Auxiliary Sphere)."
    )
    raster_input = _to_raster_function_input(raster, label)
    return arcpy.ia.Reproject(raster_input, arcpy.SpatialReference(3857))


def _to_raster_function_input(raster, label):
    candidates = []
    try:
        data_source = raster.dataSource
    except Exception:
        data_source = None
    if data_source:
        candidates.append(data_source)
    catalog_path = getattr(arcpy.Describe(raster), "catalogPath", None)
    if catalog_path and catalog_path not in candidates:
        candidates.append(catalog_path)
    candidates.append(raster)

    for candidate in candidates:
        try:
            return arcpy.Raster(candidate)
        except Exception:
            continue
    raise arcpy.ExecuteError(
        f"{label} could not be opened as a raster for the Reproject raster function. "
        "Add the source raster dataset or mosaic dataset to the active map and select it."
    )


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


def _resolve_model(local_path, item_id, file_name, messages):
    if local_path:
        messages.addMessage(f"Using custom model: {local_path}")
        return local_path
    cache_folder = DEFAULT_MODEL_CACHE

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
    analysis_extent,
    spatial_reference,
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
    cell_size_units = _meters_to_spatial_units(cell_size, spatial_reference)

    try:
        messages.addMessage(f"Detecting {feature_type.lower()} with SAM3...")
        with arcpy.EnvManager(
            gpuId=gpu_id,
            extent=analysis_extent,
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
        raw_detection_count = int(arcpy.management.GetCount(raw_features)[0])
        messages.addMessage(f"Raw SAM3 detections: {raw_detection_count}")

        messages.addMessage("Applying nonmaximum suppression to extracted features...")
        arcpy.ia.NonMaximumSuppression(
            in_featureclass=raw_features,
            confidence_score_field="Confidence",
            out_featureclass=nms_features,
            class_value_field="Class",
            max_overlap_ratio=0.1,
        )
        detection_count = int(arcpy.management.GetCount(nms_features)[0])
        messages.addMessage(f"SAM3 detections after NMS: {detection_count}")

        if FEATURE_PROFILES[feature_type]["regularize"]:
            _regularize_building_footprints(
                nms_features,
                target_features,
                spatial_reference,
                scratch_workspace,
                messages,
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


def _regularize_building_footprints(
    input_features,
    output_features,
    spatial_reference,
    scratch_workspace,
    messages,
):
    area_field = "REG_AREA"
    tolerance_bands = (
        (0, 50, 0.5),
        (50, 200, 1.0),
        (200, 500, 1.5),
        (500, 1000, 2.5),
        (1000, 4500, 3.5),
        (4500, None, 5.0),
    )
    building_layer = arcpy.CreateUniqueName("building_regularization")
    regularized_outputs = []

    try:
        arcpy.management.AddField(input_features, area_field, "DOUBLE")
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
                tolerance=_meters_to_spatial_units(
                    tolerance_meters, spatial_reference
                ),
            )

        if not regularized_outputs:
            raise arcpy.ExecuteError(
                "No valid building footprints were available for regularization."
            )
        arcpy.management.Merge(regularized_outputs, output_features)
    finally:
        if arcpy.Exists(building_layer):
            arcpy.management.Delete(building_layer)
        for dataset in regularized_outputs:
            if arcpy.Exists(dataset):
                arcpy.management.Delete(dataset)


def _select_damage_queries(
    target_features,
    sample_points,
    feature_type,
    scratch_workspace,
    messages,
):
    if feature_type == "Roads":
        return _create_road_damage_queries(
            target_features, sample_points, scratch_workspace, messages
        )

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


def _create_road_damage_queries(
    target_features, sample_points, scratch_workspace, messages
):
    sample_count = int(arcpy.management.GetCount(sample_points)[0])
    if not 6 <= sample_count <= 20:
        raise arcpy.ExecuteError(
            "Road damage examples require 6-20 point features; "
            f"{sample_count} point feature(s) were provided."
        )

    sample_layer = arcpy.CreateUniqueName("road_damage_sample_qa")
    query_features = arcpy.CreateUniqueName("road_damage_queries", scratch_workspace)
    try:
        arcpy.management.MakeFeatureLayer(sample_points, sample_layer)
        arcpy.management.SelectLayerByLocation(
            sample_layer, "INTERSECT", target_features, None, "NEW_SELECTION"
        )
        intersecting_count = int(arcpy.management.GetCount(sample_layer)[0])

        arcpy.management.SelectLayerByLocation(
            sample_layer,
            "WITHIN_A_DISTANCE",
            target_features,
            "10 Meters",
            "NEW_SELECTION",
        )
        valid_count = int(arcpy.management.GetCount(sample_layer)[0])
        nearby_count = valid_count - intersecting_count
        rejected_count = sample_count - valid_count

        messages.addMessage(
            "Road sample QA: "
            f"{intersecting_count} on inferred roads, "
            f"{nearby_count} within 10 meters, "
            f"{rejected_count} farther away."
        )
        if rejected_count:
            messages.addWarningMessage(
                f"Ignored {rejected_count} road damage point(s) more than 10 meters "
                "from an inferred road."
            )
        if valid_count < 6:
            raise arcpy.ExecuteError(
                "At least 6 road damage points must intersect or be within 10 meters "
                f"of an inferred road; {valid_count} valid point(s) remain."
            )

        arcpy.analysis.PairwiseBuffer(
            in_features=sample_layer,
            out_feature_class=query_features,
            buffer_distance_or_field="10 Meters",
            dissolve_option="NONE",
        )
        messages.addMessage(
            f"Using {valid_count} point-centered road regions as post-event damage examples."
        )
        return query_features
    except Exception:
        if arcpy.Exists(query_features):
            arcpy.management.Delete(query_features)
        raise
    finally:
        if arcpy.Exists(sample_layer):
            arcpy.management.Delete(sample_layer)


def _recommend_grid_size(target_features, post_image):
    spatial_reference = arcpy.Describe(target_features).spatialReference
    meters_per_unit = spatial_reference.metersPerUnit
    _meters_to_spatial_units(1.0, spatial_reference)
    widths = []
    with arcpy.da.SearchCursor(target_features, ["SHAPE@"]) as cursor:
        for index, (geometry,) in enumerate(cursor):
            if geometry and geometry.pointCount > 0:
                extent = geometry.extent
                width = min(extent.width, extent.height) * meters_per_unit
                if width > 0:
                    widths.append(width)
            if index >= 4999:
                break

    image_description = arcpy.Describe(post_image)
    image_spatial_reference = image_description.spatialReference
    image_cell_size = max(
        abs(float(getattr(image_description, "meanCellWidth", 0) or 0)),
        abs(float(getattr(image_description, "meanCellHeight", 0) or 0)),
    )
    image_meters_per_unit = getattr(image_spatial_reference, "metersPerUnit", None)
    if not widths or not image_cell_size or not image_meters_per_unit:
        return 5
    median_width = statistics.median(widths)
    image_cell_size_meters = image_cell_size * image_meters_per_unit
    estimated_size = int(round((1.5 * median_width) / (16.0 * image_cell_size_meters)))
    estimated_size = max(3, min(11, estimated_size))
    if estimated_size % 2 == 0:
        estimated_size += 1 if estimated_size < 11 else -1
    return estimated_size


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
import glob
import gc
import hashlib
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import uuid
from datetime import datetime, timezone
import urllib.parse
import urllib.request

import arcpy

from parameter_helpers import feature_parameter, numeric_parameter, string_parameter
from validation_helpers import (
    geodatabase_workspace as _geodatabase_workspace,
    meters_to_spatial_units as _meters_to_spatial_units,
    same_dataset as _same_dataset,
    square_meters_to_spatial_units as _square_meters_to_spatial_units,
    usable_field_names as _usable_field_names,
    validate_coverage_parameters as _validate_coverage_parameters,
    validate_example_class_field as _validate_example_class_field,
    validate_minimum_example_count as _validate_minimum_example_count,
)


TOOL_VERSION = "5.4.0"
WEB_MERCATOR_WKIDS = {3857, 102100}
WEB_MERCATOR_ORIGIN = 20037508.342787
WEB_MERCATOR_INITIAL_RESOLUTION = 156543.03392804097
MAX_WAYBACK_TILES = 4096
WAYBACK_BLOCK_TILES = 16
WAYBACK_CACHE_FORMAT_VERSION = 1
IMAGE_SERVICE_TILE_SIZE = 4000
EMBEDDING_CHUNK_PIXELS = 20000
CACHE_FORMAT_VERSION = 1
SAM3_ITEM_ID = "37ef2e1ba0c042ce99501f56295ec0d4"
EO_DINO_ITEM_ID = "93e8b9ad20734fe7a1641e46385535fc"
DUPLICATE_IOU_THRESHOLD = 0.95
BUILDING_ENVELOPE_MIN_CHILDREN = 3
BUILDING_ENVELOPE_MIN_COVERAGE = 0.02
BUILDING_ENVELOPE_MAX_COVERAGE = 0.80
EMBEDDING_MODELS = {
    "EO-DINO (Default; Multisensor/RGB)": {
        "item_id": EO_DINO_ITEM_ID,
        "file_name": "EO-DINO.dlpk",
    },
    "DINOv2 (RGB)": {
        "item_id": "17cae00c93194903a4bcb7853ab51b21",
        "file_name": "DINOv2.dlpk",
    },
    "DINOv3 (RGB)": {
        "item_id": "fbb8448003dc43aa8b69b46776606dd6",
        "file_name": "DINOv3.dlpk",
    },
}
WAYBACK_CATALOG_URL = (
    "https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/waybackconfig.json"
)
WAYBACK_MAP_SERVER_URL = (
    "https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer"
)
WORLD_IMAGERY_TILE_URL = (
    "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/"
    "MapServer/tile/{level}/{row}/{col}"
)
PORTAL_ITEM_URL = "https://www.arcgis.com/sharing/rest/content/items/{item_id}"
DEFAULT_MODEL_CACHE = os.path.join(
    os.path.expanduser("~"), "Documents", "ArcGIS", "Packages", "AutomatedFeatureExtraction"
)
FEATURE_PROFILES = {
    "Buildings": {
        "prompt": "building",
        "detection_cell_size": 0.3,
        "embedding_grid_size": 11,
        "regularize": True,
        "feature_code": "BUILDING_FOOTPRINT",
        "production_geometry": "Polygon",
        "minimum_area_sqm": 9.0,
        "maximum_gsd_m": 0.5,
        "nms_overlap": 0.6,
    },
    "Bridges": {
        "prompt": "bridge",
        "detection_cell_size": 0.3,
        "embedding_grid_size": 11,
        "regularize": False,
        "feature_code": "BRIDGE_DECK",
        "production_geometry": "Polygon",
        "minimum_area_sqm": 16.0,
        "maximum_gsd_m": 0.5,
        "nms_overlap": 0.6,
    },
    "Roads": {
        "prompt": "road",
        "detection_cell_size": 0.5,
        "embedding_grid_size": 11,
        "regularize": False,
        "feature_code": "ROAD_SURFACE_CANDIDATE",
        "production_geometry": "Polygon",
        "minimum_area_sqm": 25.0,
        "maximum_gsd_m": 0.5,
        "nms_overlap": 0.6,
        "road_aggregation_m": 1.0,
        "road_smoothing_m": 0.75,
        "road_hole_fill_sqm": 25.0,
        "road_direction_gap_m": 30.0,
        "road_direction_alignment_deg": 25.0,
    },
    "Water Bodies": {
        "prompt": "water body",
        "detection_cell_size": 0.5,
        "embedding_grid_size": 11,
        "regularize": False,
        "feature_code": "WATERBODY",
        "production_geometry": "Polygon",
        "minimum_area_sqm": 25.0,
        "maximum_gsd_m": 0.5,
        "nms_overlap": 0.6,
    },
    "Rail Corridors": {
        "prompt": "railway",
        "detection_cell_size": 0.3,
        "embedding_grid_size": 11,
        "regularize": False,
        "feature_code": "RAIL_CORRIDOR_CANDIDATE",
        "production_geometry": "Polygon",
        "minimum_area_sqm": 16.0,
        "maximum_gsd_m": 0.5,
        "nms_overlap": 0.6,
    },
    "Impervious Surfaces": {
        "prompt": "paved surface",
        "detection_cell_size": 0.3,
        "embedding_grid_size": 11,
        "regularize": False,
        "feature_code": "IMPERVIOUS_SURFACE",
        "production_geometry": "Polygon",
        "minimum_area_sqm": 16.0,
        "maximum_gsd_m": 0.5,
        "nms_overlap": 0.6,
    },
    "Parking Areas": {
        "prompt": "parking area",
        "detection_cell_size": 0.3,
        "embedding_grid_size": 11,
        "regularize": False,
        "feature_code": "PARKING_AREA",
        "production_geometry": "Polygon",
        "minimum_area_sqm": 25.0,
        "maximum_gsd_m": 0.5,
        "nms_overlap": 0.6,
    },
    "Solar Arrays": {
        "prompt": "solar panel array",
        "detection_cell_size": 0.2,
        "embedding_grid_size": 9,
        "regularize": False,
        "feature_code": "SOLAR_ARRAY",
        "production_geometry": "Polygon",
        "minimum_area_sqm": 4.0,
        "maximum_gsd_m": 0.3,
        "nms_overlap": 0.6,
    },
    "Sports Surfaces": {
        "prompt": "sports field",
        "detection_cell_size": 0.3,
        "embedding_grid_size": 11,
        "regularize": False,
        "feature_code": "SPORTS_SURFACE",
        "production_geometry": "Polygon",
        "minimum_area_sqm": 100.0,
        "maximum_gsd_m": 0.5,
        "nms_overlap": 0.6,
    },
    "Swimming Pools": {
        "prompt": "swimming pool",
        "detection_cell_size": 0.2,
        "embedding_grid_size": 9,
        "regularize": False,
        "feature_code": "SWIMMING_POOL",
        "production_geometry": "Polygon",
        "minimum_area_sqm": 8.0,
        "maximum_gsd_m": 0.3,
        "nms_overlap": 0.6,
    },
    "Construction Areas": {
        "prompt": "construction site",
        "detection_cell_size": 0.3,
        "embedding_grid_size": 9,
        "regularize": False,
        "feature_code": "CONSTRUCTION_OBSERVATION",
        "production_geometry": "Polygon",
        "minimum_area_sqm": 25.0,
        "maximum_gsd_m": 0.5,
        "nms_overlap": 0.6,
    },
    "Material Stockpiles": {
        "prompt": "material stockpile",
        "detection_cell_size": 0.2,
        "embedding_grid_size": 7,
        "regularize": False,
        "feature_code": "STOCKPILE_OBSERVATION",
        "production_geometry": "Polygon",
        "minimum_area_sqm": 9.0,
        "maximum_gsd_m": 0.3,
        "nms_overlap": 0.6,
    },
    "Bare Ground": {
        "prompt": "bare ground",
        "detection_cell_size": 0.3,
        "embedding_grid_size": 11,
        "regularize": False,
        "feature_code": "BARE_GROUND_CANDIDATE",
        "production_geometry": "Polygon",
        "minimum_area_sqm": 25.0,
        "maximum_gsd_m": 0.5,
        "nms_overlap": 0.6,
    },
    "Flooded Areas": {
        "prompt": "flooded area",
        "detection_cell_size": 0.3,
        "embedding_grid_size": 9,
        "regularize": False,
        "feature_code": "FLOOD_OBSERVATION",
        "production_geometry": "Polygon",
        "minimum_area_sqm": 25.0,
        "maximum_gsd_m": 0.5,
        "nms_overlap": 0.6,
    },
    "Debris": {
        "prompt": "debris",
        "detection_cell_size": 0.2,
        "embedding_grid_size": 1,
        "regularize": False,
        "feature_code": "DEBRIS_OBSERVATION",
        "production_geometry": "Polygon",
        "minimum_area_sqm": 4.0,
        "maximum_gsd_m": 0.3,
        "nms_overlap": 0.6,
    },
    "Vehicles": {
        "prompt": "vehicle",
        "detection_cell_size": 0.15,
        "embedding_grid_size": 1,
        "regularize": False,
        "feature_code": "VEHICLE_OBSERVATION",
        "production_geometry": "Polygon",
        "minimum_area_sqm": 2.0,
        "maximum_gsd_m": 0.2,
        "nms_overlap": 0.6,
    },
    "Trees": {
        "prompt": "tree",
        "detection_cell_size": 0.2,
        "embedding_grid_size": 9,
        "regularize": False,
        "feature_code": "TREE_CANOPY",
        "production_geometry": "Polygon",
        "minimum_area_sqm": 4.0,
        "maximum_gsd_m": 0.3,
        "nms_overlap": 0.6,
    },
    "Forest Cover": {
        "prompt": "forest canopy",
        "detection_cell_size": 0.5,
        "embedding_grid_size": 11,
        "regularize": False,
        "feature_code": "FOREST_COVER_CANDIDATE",
        "production_geometry": "Polygon",
        "minimum_area_sqm": 100.0,
        "maximum_gsd_m": 0.5,
        "nms_overlap": 0.6,
    },
    "Agricultural Fields": {
        "prompt": "agricultural field",
        "detection_cell_size": 0.5,
        "embedding_grid_size": 11,
        "regularize": False,
        "feature_code": "AGRICULTURAL_COVER_CANDIDATE",
        "production_geometry": "Polygon",
        "minimum_area_sqm": 100.0,
        "maximum_gsd_m": 0.5,
        "nms_overlap": 0.6,
        "field_hole_fill_sqm": 100.0,
        "field_fragment_max_sqm": 100.0,
        "field_smoothing_m": 0.5,
    },
    "Park-Like Green Space": {
        "prompt": "park green space",
        "detection_cell_size": 0.3,
        "embedding_grid_size": 11,
        "regularize": False,
        "feature_code": "GREEN_SPACE_OBSERVATION",
        "production_geometry": "Polygon",
        "minimum_area_sqm": 100.0,
        "maximum_gsd_m": 0.5,
        "nms_overlap": 0.6,
    },
    "Utility Poles": {
        "prompt": "utility pole",
        "detection_cell_size": 0.1,
        "embedding_grid_size": 7,
        "regularize": False,
        "feature_code": "UTILITY_POLE_OBSERVATION",
        "production_geometry": "Polygon",
        "minimum_area_sqm": 0.25,
        "maximum_gsd_m": 0.15,
        "nms_overlap": 0.6,
    },
    "Other Structures": {
        "prompt": "structure",
        "detection_cell_size": 0.3,
        "embedding_grid_size": 9,
        "regularize": False,
        "feature_code": "OTHER_STRUCTURE",
        "production_geometry": "Polygon",
        "minimum_area_sqm": 4.0,
        "maximum_gsd_m": 0.5,
        "nms_overlap": 0.6,
    },
    "Custom": {
        "prompt": "",
        "detection_cell_size": 0.3,
        "embedding_grid_size": 7,
        "regularize": False,
        "feature_code": "CUSTOM_CANDIDATE",
        "production_geometry": "Polygon",
        "minimum_area_sqm": 0.0,
        "maximum_gsd_m": None,
        "nms_overlap": 0.6,
    },
}


def _feature_type_choices():
    return sorted(
        (feature_type for feature_type in FEATURE_PROFILES if feature_type != "Custom"),
        key=str.casefold,
    ) + ["Custom"]


DEFAULT_WORKFLOWS = {
    "Debris": "Embedding Similarity",
    "Vehicles": "Damage Assessment",
}
FEATURE_WORKFLOWS = {
    "Debris": ("Feature Extraction", "Embedding Similarity"),
    "Custom": (
        "Feature Extraction",
        "Embedding Similarity",
        "Damage Assessment",
    ),
    "Vehicles": ("Damage Assessment",),
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
        self.label = "Automated Feature Extraction and Classification"
        self.alias = "automatedfeatureextraction"
        self.tools = [AutomatedFeatureExtraction]


class AutomatedFeatureExtraction(object):
    FEATURE_TYPE = 0
    WORKFLOW = 1
    IN_TARGET = 2
    AOI = 3
    EXTRACTION_SOURCE = 4
    EXTRACTION_IMAGE = 5
    EXTRACTION_WAYBACK = 6
    SAM_MODEL = 7
    CUSTOM_PROMPT = 8
    DETECTION_CELL_SIZE = 9
    ANALYSIS_SOURCE = 10
    ANALYSIS_IMAGE = 11
    ANALYSIS_WAYBACK = 12
    SAMPLE_POINTS = 13
    CLASS_FIELD = 14
    ONLINE_EMBEDDING_MODEL = 15
    EMBEDDING_MODEL = 16
    GPU_ID = 17
    BATCH_SIZE = 18
    GRID_SIZE = 19
    SIMILARITY_THRESHOLD = 20
    OUT_FEATURES = 21
    OUT_EMBEDDINGS = 22
    OUT_SIMILAR = 23
    KEEP_INTERMEDIATE = 24
    EXISTING_EMBEDDINGS = 25

    def __init__(self):
        self.label = "Automated Feature Extraction and Classification"
        self.description = (
            "Extracts named feature types with SAM3, finds imagery that resembles "
            "example points, or classifies supplied or extracted target features "
            "with user-defined classes."
        )
        self.canRunInBackground = False
        self.environments = ["extent"]
        self._last_feature_type = None
        self._last_wayback_filter_key = None
        self._filtered_wayback_releases = None

    def getParameterInfo(self):
        feature_type = string_parameter(
            "Feature Type", "feature_type", "Feature Definition", "Buildings",
            _feature_type_choices(), True,
        )
        workflow = string_parameter(
            "Workflow", "workflow", "Feature Definition", "Feature Extraction",
            ("Feature Extraction", "Embedding Similarity", "Feature Classification"), True,
        )
        in_target = feature_parameter(
            "Input Features to Classify (Optional)", "in_target_features",
            "Feature Definition", ["Polygon"],
        )
        aoi = feature_parameter(
            "Area of Interest Polygon (Optional; Overrides Extent)", "in_aoi",
            "Feature Definition", ["Polygon"],
        )
        extraction_source = string_parameter(
            "Feature Extraction Imagery Source", "extraction_source",
            "Feature Extraction", "Input Imagery",
            ("Input Imagery", "World Imagery Wayback"), True,
        )
        extraction_image = string_parameter(
            "Feature Extraction Imagery Layer (from Active Map)", "in_extraction_imagery",
            "Feature Extraction", None, _get_active_map_raster_layer_names(),
        )
        extraction_wayback = string_parameter(
            "Feature Extraction World Imagery Wayback Release", "extraction_wayback_release",
            "Feature Extraction", None, (),
        )
        sam_model = arcpy.Parameter(
            displayName="Custom Extraction Model (.dlpk, Optional; Default: Living Atlas SAM3)",
            name="in_sam_model", datatype="DEFile", parameterType="Optional", direction="Input",
        )
        sam_model.filter.list = ["dlpk"]
        sam_model.category = "Feature Extraction"
        custom_prompt = arcpy.Parameter(
            displayName="Custom SAM3 Text Prompt", name="custom_sam_prompt",
            datatype="GPString", parameterType="Optional", direction="Input",
        )
        custom_prompt.category = "Feature Extraction"
        detection_cell_size = arcpy.Parameter(
            displayName="Feature Detection Cell Size", name="detection_cell_size",
            datatype="GPDouble", parameterType="Optional", direction="Input",
        )
        detection_cell_size.value = FEATURE_PROFILES["Buildings"]["detection_cell_size"]
        detection_cell_size.category = "Feature Extraction"
        analysis_source = string_parameter(
            "Similarity Analysis Imagery Source", "analysis_source", "Similarity Analysis",
            "Input Imagery", ("Input Imagery", "Current World Imagery", "World Imagery Wayback"), True,
        )
        analysis_image = string_parameter(
            "Similarity Analysis Imagery Layer (from Active Map)", "in_analysis_imagery",
            "Similarity Analysis", None, _get_active_map_raster_layer_names(),
        )
        analysis_wayback = string_parameter(
            "Similarity Analysis World Imagery Wayback Release", "analysis_wayback_release",
            "Similarity Analysis", None, (),
        )
        sample_points = feature_parameter(
            "Classified Example Points (Minimum 6 per Class)", "in_example_points",
            "Similarity Analysis", ["Point", "Multipoint"],
        )
        class_field = string_parameter(
            "Example Class Field", "example_class_field", "Similarity Analysis",
            None, (),
        )
        online_embedding_model = string_parameter(
            "ArcGIS Online Embedding Model", "online_embedding_model", "Similarity Analysis",
            next(iter(EMBEDDING_MODELS)), list(EMBEDDING_MODELS), True,
        )
        embedding_model = arcpy.Parameter(
            displayName="Custom Embedding Model (.dlpk, Optional Override)",
            name="in_embedding_model", datatype="DEFile", parameterType="Optional", direction="Input",
        )
        embedding_model.filter.list = ["dlpk"]
        embedding_model.category = "Similarity Analysis"
        gpu_id = numeric_parameter("GPU ID", "gpu_id", "GPLong", "Similarity Analysis", 0)
        batch_size = numeric_parameter("Batch Size", "batch_size", "GPLong", "Similarity Analysis", 4)
        grid_size = numeric_parameter("Embedding Grid Size (Optional; Blank = Auto)", "grid_size", "GPLong", "Similarity Analysis")
        similarity_threshold = numeric_parameter("Similarity Threshold", "similarity_threshold", "GPDouble", "Similarity Analysis", 0.55)
        out_features = arcpy.Parameter(
            displayName="Output Features", name="out_features", datatype="DEFeatureClass",
            parameterType="Required", direction="Output",
        )
        out_features.category = "Outputs"
        out_embeddings = arcpy.Parameter(
            displayName="Embeddings", name="out_embeddings", datatype="DEFeatureClass",
            parameterType="Derived", direction="Output",
        )
        out_embeddings.category = "Outputs"
        out_embeddings.addToMap = False
        out_similar = arcpy.Parameter(
            displayName="Similar Features", name="out_similar_features", datatype="DEFeatureClass",
            parameterType="Derived", direction="Output",
        )
        out_similar.category = "Outputs"
        out_similar.addToMap = False
        keep_intermediate = arcpy.Parameter(
            displayName="Keep Intermediate Data", name="keep_intermediate_data",
            datatype="GPBoolean", parameterType="Optional", direction="Input",
        )
        keep_intermediate.value = True
        keep_intermediate.category = "Outputs"
        existing_embeddings = feature_parameter(
            "Existing Embeddings (Optional; Skips Generation)", "in_existing_embeddings",
            "Similarity Analysis", ["Polygon"],
        )
        return [
            feature_type, workflow, in_target, aoi, extraction_source, extraction_image,
            extraction_wayback, sam_model, custom_prompt, detection_cell_size,
            analysis_source, analysis_image, analysis_wayback, sample_points,
            class_field, online_embedding_model, embedding_model, gpu_id, batch_size,
            grid_size, similarity_threshold, out_features, out_embeddings, out_similar,
            keep_intermediate, existing_embeddings,
        ]

    def updateParameters(self, parameters):
        feature_type = parameters[self.FEATURE_TYPE].valueAsText or "Buildings"
        workflow = parameters[self.WORKFLOW].valueAsText or "Feature Extraction"
        has_target_features = bool(parameters[self.IN_TARGET].valueAsText)
        requires_extraction = workflow == "Feature Extraction" or (
            workflow == "Feature Classification" and not has_target_features
        )
        requires_similarity = workflow in ("Embedding Similarity", "Feature Classification")
        has_existing_embeddings = bool(parameters[self.EXISTING_EMBEDDINGS].valueAsText)
        if feature_type != self._last_feature_type:
            parameters[self.DETECTION_CELL_SIZE].value = FEATURE_PROFILES[feature_type]["detection_cell_size"]
            self._last_feature_type = feature_type
        for index in (self.EXTRACTION_SOURCE, self.EXTRACTION_IMAGE, self.EXTRACTION_WAYBACK,
                      self.SAM_MODEL, self.DETECTION_CELL_SIZE):
            parameters[index].enabled = requires_extraction
        parameters[self.IN_TARGET].enabled = workflow == "Feature Classification"
        parameters[self.CUSTOM_PROMPT].enabled = requires_extraction and feature_type == "Custom"
        extraction_source = parameters[self.EXTRACTION_SOURCE].valueAsText or "Input Imagery"
        parameters[self.EXTRACTION_IMAGE].enabled = requires_extraction and extraction_source == "Input Imagery"
        parameters[self.EXTRACTION_WAYBACK].enabled = requires_extraction and extraction_source == "World Imagery Wayback"
        for index in (self.ANALYSIS_SOURCE, self.ONLINE_EMBEDDING_MODEL, self.EMBEDDING_MODEL,
                      self.GPU_ID, self.BATCH_SIZE, self.GRID_SIZE):
            parameters[index].enabled = requires_similarity and not has_existing_embeddings
        analysis_source = parameters[self.ANALYSIS_SOURCE].valueAsText or "Input Imagery"
        parameters[self.ANALYSIS_IMAGE].enabled = (
            requires_similarity and not has_existing_embeddings and analysis_source == "Input Imagery"
        )
        parameters[self.ANALYSIS_WAYBACK].enabled = (
            requires_similarity and not has_existing_embeddings and analysis_source == "World Imagery Wayback"
        )
        parameters[self.SAMPLE_POINTS].enabled = requires_similarity
        parameters[self.CLASS_FIELD].enabled = workflow == "Feature Classification"
        parameters[self.SIMILARITY_THRESHOLD].enabled = requires_similarity
        parameters[self.EXISTING_EMBEDDINGS].enabled = requires_similarity
        raster_layer_names = _get_active_map_raster_layer_names()
        parameters[self.EXTRACTION_IMAGE].filter.list = raster_layer_names
        parameters[self.ANALYSIS_IMAGE].filter.list = raster_layer_names
        parameters[self.CLASS_FIELD].filter.list = _usable_field_names(
            parameters[self.SAMPLE_POINTS].valueAsText
        )
        self._update_wayback_parameters(parameters, requires_extraction, requires_similarity,
                                        has_existing_embeddings, extraction_source, analysis_source)

    def _update_wayback_parameters(self, parameters, requires_extraction, requires_similarity,
                                   has_existing_embeddings, extraction_source, analysis_source):
        uses_wayback = (
            (requires_extraction and extraction_source == "World Imagery Wayback")
            or (requires_similarity and not has_existing_embeddings and analysis_source == "World Imagery Wayback")
        )
        if not uses_wayback:
            return
        filter_extent = _get_wayback_filter_extent(parameters[self.AOI].valueAsText, None)
        filter_key = _wayback_filter_key(filter_extent)
        if filter_key != self._last_wayback_filter_key:
            self._last_wayback_filter_key = filter_key
            try:
                self._filtered_wayback_releases = (
                    _get_wayback_releases_with_local_changes(*filter_extent) if filter_extent else None
                )
            except Exception:
                self._filtered_wayback_releases = None
        releases = self._filtered_wayback_releases or _get_wayback_releases()
        choices = [release[0] for release in releases]
        parameters[self.EXTRACTION_WAYBACK].filter.list = choices
        parameters[self.ANALYSIS_WAYBACK].filter.list = choices

    def updateMessages(self, parameters):
        workflow = parameters[self.WORKFLOW].valueAsText or "Feature Extraction"
        requires_similarity = workflow in ("Embedding Similarity", "Feature Classification")
        requires_extraction = workflow == "Feature Extraction" or (
            workflow == "Feature Classification"
            and not parameters[self.IN_TARGET].valueAsText
        )
        sample_points = parameters[self.SAMPLE_POINTS].valueAsText
        existing_embeddings = parameters[self.EXISTING_EMBEDDINGS].valueAsText
        if requires_extraction:
            _set_positive_error(parameters[self.DETECTION_CELL_SIZE], "Detection cell size")
        if requires_similarity:
            _set_positive_error(parameters[self.GRID_SIZE], "Grid size")
            similarity = parameters[self.SIMILARITY_THRESHOLD].value
            if similarity is not None and not 0 < float(similarity) <= 1:
                parameters[self.SIMILARITY_THRESHOLD].setErrorMessage(
                    "Similarity threshold must be greater than 0 and at most 1."
                )
            if existing_embeddings and not _has_embedding_field(existing_embeddings):
                parameters[self.EXISTING_EMBEDDINGS].setErrorMessage(
                    "Existing embeddings must contain a BLOB embedding field."
                )
            if workflow == "Feature Classification":
                _validate_example_class_field(
                    sample_points, parameters[self.CLASS_FIELD].valueAsText,
                    parameters[self.CLASS_FIELD],
                )
            elif sample_points:
                _validate_minimum_example_count(sample_points, parameters[self.SAMPLE_POINTS])
        output_path = parameters[self.OUT_FEATURES].valueAsText
        if output_path and (
            _same_dataset(output_path, existing_embeddings)
            or _same_dataset(output_path, parameters[self.IN_TARGET].valueAsText)
        ):
            parameters[self.OUT_FEATURES].setErrorMessage(
                "Output Features must differ from input features and existing embeddings."
            )
        elif output_path and not _geodatabase_workspace(output_path):
            parameters[self.OUT_FEATURES].setErrorMessage(
                "Output Features must be stored in a file or enterprise geodatabase."
            )

    def execute(self, parameters, messages):
        with arcpy.EnvManager(addOutputsToMap=False):
            self._execute_internal(parameters, messages)

    def _execute_internal(self, parameters, messages):
        workflow = parameters[self.WORKFLOW].valueAsText or "Feature Extraction"
        feature_type = parameters[self.FEATURE_TYPE].valueAsText or "Buildings"
        profile = FEATURE_PROFILES[feature_type]
        aoi = parameters[self.AOI].valueAsText
        out_features = parameters[self.OUT_FEATURES].valueAsText
        output_workspace = _geodatabase_workspace(out_features)
        if not output_workspace:
            raise arcpy.ExecuteError("Output Features must be stored in a file or enterprise geodatabase.")
        messages.addMessage(f"Automated Feature Extraction and Classification version {TOOL_VERSION}")
        messages.addMessage(f"Workflow: {workflow}; feature type: {feature_type}")
        candidate_context = {
            "run_id": str(uuid.uuid4()),
            "workflow": workflow,
            "feature_type": feature_type,
            "source_image": None,
            "model_id": None,
            "model_file": None,
        }
        target_features = parameters[self.IN_TARGET].valueAsText
        if target_features:
            candidate_context["source_image"] = _dataset_label(target_features)
        generated_target_features = None
        requires_extraction = workflow == "Feature Extraction" or (
            workflow == "Feature Classification" and not target_features
        )
        if requires_extraction:
            _validate_gpu_memory(int(parameters[self.GPU_ID].value or 0), messages)
            source = _resolve_extraction_source(parameters, aoi, messages)
            candidate_context["source_image"] = _dataset_label(source)
            detection_cell_size = float(
                parameters[self.DETECTION_CELL_SIZE].value or FEATURE_PROFILES[feature_type]["detection_cell_size"]
            )
            model = _resolve_model(parameters[self.SAM_MODEL].valueAsText, SAM3_ITEM_ID, "SAM3.dlpk", messages)
            candidate_context["model_id"] = SAM3_ITEM_ID
            candidate_context["model_file"] = model
            extent, spatial_reference, _ = _resolve_analysis_extent(aoi, source, True)
            target_features = _extract_target_features(
                source, extent, spatial_reference, feature_type,
                parameters[self.CUSTOM_PROMPT].valueAsText or FEATURE_PROFILES[feature_type]["prompt"],
                model, detection_cell_size, int(parameters[self.BATCH_SIZE].value or 4),
                int(parameters[self.GPU_ID].value or 0), output_workspace, out_features,
                arcpy.env.scratchGDB, messages,
            )
            generated_target_features = target_features
        if workflow == "Feature Extraction":
            _publish_candidate_features(
                target_features, out_features, profile, candidate_context, messages
            )
            if generated_target_features and arcpy.Exists(generated_target_features):
                arcpy.management.Delete(generated_target_features)
            return
        self._execute_similarity(
            parameters, messages, workflow, feature_type, aoi, output_workspace,
            out_features, target_features, generated_target_features, candidate_context,
        )

    def _execute_similarity(
        self, parameters, messages, workflow, feature_type, aoi, output_workspace,
        out_features, target_features, generated_target_features, candidate_context,
    ):
        existing_embeddings = parameters[self.EXISTING_EMBEDDINGS].valueAsText
        sample_points = parameters[self.SAMPLE_POINTS].valueAsText
        if not sample_points:
            raise arcpy.ExecuteError("Provide example points for similarity analysis.")
        generated_embeddings = None
        out_similar = None
        seed_evidence = None
        if existing_embeddings:
            out_embeddings = existing_embeddings
            messages.addMessage("Using existing embeddings; imagery preparation and generation are skipped.")
        else:
            gpu_id = int(parameters[self.GPU_ID].value or 0)
            _validate_gpu_memory(gpu_id, messages)
            source, extent, spatial_reference = _resolve_similarity_source(parameters, aoi, messages)
            selected_model = EMBEDDING_MODELS[parameters[self.ONLINE_EMBEDDING_MODEL].valueAsText]
            custom_model = parameters[self.EMBEDDING_MODEL].valueAsText
            model = _resolve_model(custom_model, selected_model["item_id"], selected_model["file_name"], messages)
            model_signature = _embedding_model_signature(
                model, selected_model["item_id"], bool(custom_model)
            )
            candidate_context["source_image"] = _dataset_label(source)
            candidate_context["model_id"] = model_signature
            candidate_context["model_file"] = model
            grid_size = int(parameters[self.GRID_SIZE].value or FEATURE_PROFILES[feature_type]["embedding_grid_size"])
            source = _ensure_web_mercator_raster(source, "Similarity analysis imagery", messages)
            out_embeddings = _find_compatible_embeddings(
                output_workspace, _dataset_label(source), model_signature,
                grid_size, arcpy.Describe(source).spatialReference, extent,
            )
            if out_embeddings:
                messages.addMessage(
                    f"Reusing compatible embeddings from the output geodatabase: {out_embeddings}"
                )
            else:
                out_embeddings = arcpy.CreateUniqueName(
                    f"{_output_name_prefix(out_features)}_Embeddings", output_workspace
                )
                generated_embeddings = out_embeddings
                _generate_embeddings(
                    source, out_embeddings, model, int(parameters[self.BATCH_SIZE].value or 4), grid_size,
                    gpu_id, extent, spatial_reference, arcpy.Describe(source).spatialReference, None, messages,
                )
                _write_embedding_signature(
                    out_embeddings, _dataset_label(source), model_signature,
                    grid_size, arcpy.Describe(source).spatialReference,
                )
        parameters[self.OUT_EMBEDDINGS].value = out_embeddings
        try:
            out_similar = arcpy.CreateUniqueName(
                f"{_output_name_prefix(out_features)}_Similar", output_workspace
            )
            threshold = float(parameters[self.SIMILARITY_THRESHOLD].value or 0.55)
            if workflow == "Feature Classification":
                seed_evidence = arcpy.CreateUniqueName(
                    f"{_output_name_prefix(out_features)}_ClassSeeds", output_workspace
                )
                _find_classified_similar_features(
                    out_embeddings, target_features, sample_points,
                    parameters[self.CLASS_FIELD].valueAsText, feature_type, out_similar,
                    seed_evidence, threshold, arcpy.env.scratchGDB, messages,
                )
            else:
                queries = _select_embedding_queries(out_embeddings, sample_points, arcpy.env.scratchGDB, messages)
                try:
                    arcpy.geoai.FindSimilarFeaturesUsingEmbeddings(
                        embedding_features=out_embeddings, query_features=queries,
                        out_embeddings_feature_class=out_similar, threshold=threshold,
                    )
                finally:
                    if arcpy.Exists(queries):
                        arcpy.management.Delete(queries)
            parameters[self.OUT_SIMILAR].value = out_similar
            staged_features = arcpy.CreateUniqueName(
                f"{_output_name_prefix(out_features)}_CandidateStage", output_workspace
            )
            if workflow == "Feature Classification":
                _classify_target_features(
                    target_features, out_similar, seed_evidence, staged_features, arcpy.env.scratchGDB,
                    messages,
                )
            else:
                arcpy.management.CopyFeatures(out_similar, staged_features)
            _publish_candidate_features(
                staged_features, out_features, FEATURE_PROFILES[feature_type],
                candidate_context, messages,
            )
            arcpy.management.Delete(staged_features)
        finally:
            if not parameters[self.KEEP_INTERMEDIATE].value:
                for dataset in (out_similar, seed_evidence, generated_embeddings, generated_target_features):
                    if dataset and arcpy.Exists(dataset):
                        arcpy.management.Delete(dataset)
                parameters[self.OUT_SIMILAR].value = None
                if generated_embeddings:
                    parameters[self.OUT_EMBEDDINGS].value = None


def _output_name_prefix(output_features):
    base_name = os.path.basename(output_features or "AutomatedFeatures")
    return re.sub("[^A-Za-z0-9_]+", "_", base_name).strip("_") or "AutomatedFeatures"


def _dataset_label(dataset):
    if not dataset:
        return None
    try:
        return arcpy.Describe(dataset).catalogPath
    except Exception:
        return str(dataset)


def _spatial_reference_key(spatial_reference):
    factory_code = getattr(spatial_reference, "factoryCode", 0)
    return str(factory_code or getattr(spatial_reference, "name", ""))


def _embedding_model_signature(model_path, online_item_id, is_custom_model):
    if not is_custom_model:
        return online_item_id
    model_stat = os.stat(model_path)
    signature_input = f"{os.path.abspath(model_path)}|{model_stat.st_size}|{model_stat.st_mtime_ns}"
    return hashlib.sha256(signature_input.encode("utf-8")).hexdigest()


def _extent_contains(container_extent, requested_extent, tolerance=1e-6):
    return (
        container_extent.XMin <= requested_extent.XMin + tolerance
        and container_extent.YMin <= requested_extent.YMin + tolerance
        and container_extent.XMax >= requested_extent.XMax - tolerance
        and container_extent.YMax >= requested_extent.YMax - tolerance
    )


def _write_embedding_signature(embedding_features, source_image, model_item_id, grid_size, spatial_reference):
    signature_fields = (
        ("AFE_EMB_SOURCE", "TEXT", 1000),
        ("AFE_EMB_MODEL", "TEXT", 64),
        ("AFE_EMB_GRID", "LONG", None),
        ("AFE_EMB_CRS", "TEXT", 128),
    )
    existing_fields = {field.name.upper() for field in arcpy.ListFields(embedding_features)}
    for field_name, field_type, field_length in signature_fields:
        if field_name.upper() not in existing_fields:
            add_kwargs = {"field_name": field_name, "field_type": field_type}
            if field_length:
                add_kwargs["field_length"] = field_length
            arcpy.management.AddField(embedding_features, **add_kwargs)
    values = (source_image, model_item_id, int(grid_size), _spatial_reference_key(spatial_reference))
    with arcpy.da.UpdateCursor(
        embedding_features, [field_name for field_name, _, _ in signature_fields]
    ) as cursor:
        for _ in cursor:
            cursor.updateRow(values)


def _find_compatible_embeddings(
    workspace, source_image, model_item_id, grid_size, spatial_reference, requested_extent,
):
    required_fields = ("AFE_EMB_SOURCE", "AFE_EMB_MODEL", "AFE_EMB_GRID", "AFE_EMB_CRS")
    source_key = os.path.normcase(os.path.normpath(source_image))
    spatial_reference_key = _spatial_reference_key(spatial_reference)
    try:
        for directory, _, feature_classes in arcpy.da.Walk(workspace, datatype="FeatureClass"):
            for feature_class_name in feature_classes:
                feature_class = os.path.join(directory, feature_class_name)
                if not _has_embedding_field(feature_class):
                    continue
                field_names = {field.name.upper() for field in arcpy.ListFields(feature_class)}
                if not all(field_name in field_names for field_name in required_fields):
                    continue
                with arcpy.da.SearchCursor(feature_class, required_fields) as cursor:
                    signature = next(cursor, None)
                if not signature:
                    continue
                candidate_source, candidate_model, candidate_grid, candidate_crs = signature
                if (
                    not candidate_source
                    or os.path.normcase(os.path.normpath(candidate_source)) != source_key
                    or candidate_model != model_item_id
                    or candidate_grid != int(grid_size)
                    or candidate_crs != spatial_reference_key
                ):
                    continue
                if _extent_contains(arcpy.Describe(feature_class).extent, requested_extent):
                    return feature_class
    except Exception:
        return None
    return None


def _publish_candidate_features(input_features, output_features, profile, context, messages):
    """Atomically publish an auditable candidate layer without discarding QA failures."""
    output_workspace = _geodatabase_workspace(output_features)
    staged_features = arcpy.CreateUniqueName(
        f"{_output_name_prefix(output_features)}_PublishStage", output_workspace
    )
    fields = (
        ("AFE_RUN_ID", "TEXT", 36),
        ("FEATURE_CODE", "TEXT", 64),
        ("FEATURE_TYPE", "TEXT", 64),
        ("GEOM_ROLE", "TEXT", 32),
        ("QC_STATUS", "TEXT", 32),
        ("QC_REASON", "TEXT", 255),
        ("TOOL_VERSION", "TEXT", 32),
        ("PROFILE_VER", "TEXT", 16),
        ("SOURCE_IMAGE", "TEXT", 1000),
        ("MODEL_ITEM_ID", "TEXT", 64),
        ("MODEL_FILE", "TEXT", 1000),
        ("RUN_UTC", "DATE", None),
        ("AREA_SQM", "DOUBLE", None),
    )
    try:
        arcpy.management.CopyFeatures(input_features, staged_features)
        existing_fields = {field.name.upper() for field in arcpy.ListFields(staged_features)}
        for field_name, field_type, field_length in fields:
            if field_name.upper() not in existing_fields:
                add_kwargs = {"field_name": field_name, "field_type": field_type}
                if field_length:
                    add_kwargs["field_length"] = field_length
                arcpy.management.AddField(staged_features, **add_kwargs)
        minimum_area = float(profile["minimum_area_sqm"])
        run_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        with arcpy.da.UpdateCursor(
            staged_features,
            ["SHAPE@", "AFE_RUN_ID", "FEATURE_CODE", "FEATURE_TYPE", "GEOM_ROLE",
             "QC_STATUS", "QC_REASON", "TOOL_VERSION", "PROFILE_VER", "SOURCE_IMAGE",
             "MODEL_ITEM_ID", "MODEL_FILE", "RUN_UTC", "AREA_SQM"],
        ) as cursor:
            for row in cursor:
                geometry = row[0]
                area_sqm = geometry.getArea("GEODESIC", "SQUAREMETERS") if geometry else 0.0
                if not geometry or area_sqm <= 0:
                    qc_status, qc_reason = "Rejected", "Empty, null, or zero-area geometry"
                elif area_sqm < minimum_area:
                    qc_status = "Rejected"
                    qc_reason = f"Area below profile minimum of {minimum_area:g} square meters"
                elif profile["feature_code"] == "CUSTOM_CANDIDATE":
                    qc_status, qc_reason = "NeedsReview", "Custom profile has no governed production specification"
                else:
                    qc_status, qc_reason = "NeedsReview", "Automated candidate requires topographic review"
                row[1:] = [
                    context["run_id"], profile["feature_code"], context["feature_type"],
                    "Candidate" if context["workflow"] == "Feature Classification" else "Evidence",
                    qc_status, qc_reason, TOOL_VERSION, "1.0",
                    context.get("source_image"), context.get("model_id"), context.get("model_file"),
                    run_utc, area_sqm,
                ]
                cursor.updateRow(row)
        if arcpy.Exists(output_features):
            arcpy.management.Delete(output_features)
        arcpy.management.CopyFeatures(staged_features, output_features)
        messages.addMessage(
            "Published an auditable candidate layer. QC_STATUS is NeedsReview or Rejected; "
            "no feature has been accepted as authoritative topographic data."
        )
    finally:
        if arcpy.Exists(staged_features):
            arcpy.management.Delete(staged_features)


def _resolve_extraction_source(parameters, aoi, messages):
    source_type = parameters[AutomatedFeatureExtraction.EXTRACTION_SOURCE].valueAsText
    if source_type == "Input Imagery":
        source = _resolve_active_map_raster_layer(
            parameters[AutomatedFeatureExtraction.EXTRACTION_IMAGE].valueAsText
        )
        return _ensure_web_mercator_raster(source, "Feature extraction imagery", messages)
    extent, spatial_reference, _ = _resolve_analysis_extent(aoi, None, True)
    release = parameters[AutomatedFeatureExtraction.EXTRACTION_WAYBACK].valueAsText
    cell_size = float(
        parameters[AutomatedFeatureExtraction.DETECTION_CELL_SIZE].value
        or FEATURE_PROFILES[parameters[AutomatedFeatureExtraction.FEATURE_TYPE].valueAsText]["detection_cell_size"]
    )
    metadata = _validate_wayback_coverage(
        release, extent, spatial_reference, "Feature extraction", messages
    )
    return _materialize_wayback_imagery(
        release, extent, spatial_reference, _wayback_cell_size(metadata, cell_size),
        "FeatureExtraction", messages,
    )


def _resolve_similarity_source(parameters, aoi, messages):
    source_type = parameters[AutomatedFeatureExtraction.ANALYSIS_SOURCE].valueAsText
    if source_type == "Input Imagery":
        source = _resolve_active_map_raster_layer(
            parameters[AutomatedFeatureExtraction.ANALYSIS_IMAGE].valueAsText
        )
        source = _ensure_web_mercator_raster(source, "Similarity analysis imagery", messages)
        extent, spatial_reference, _ = _resolve_analysis_extent(aoi, source, True)
    else:
        extent, spatial_reference, _ = _resolve_analysis_extent(aoi, None, True)
        source = None
    source, _, _ = _resolve_post_event_imagery(
        source_type,
        source,
        parameters[AutomatedFeatureExtraction.ANALYSIS_WAYBACK].valueAsText,
        extent,
        spatial_reference,
        messages,
    )
    return source, extent, spatial_reference


def _find_classified_similar_features(
    embedding_features, target_features, sample_points, class_field, feature_type, output_features,
    seed_output_features, threshold,
    scratch_workspace, messages,
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
        value: _class_value_label(sample_points, class_field, value)
        for value in class_values
    }
    sample_layer = arcpy.CreateUniqueName("classified_example_points", scratch_workspace)
    class_outputs = []
    seed_outputs = []
    try:
        arcpy.management.MakeFeatureLayer(sample_points, sample_layer)
        field_delimiter = arcpy.AddFieldDelimiters(sample_points, class_field)
        field_type = next(field.type for field in arcpy.ListFields(sample_points) if field.name == class_field)
        for index, value in enumerate(class_values, start=1):
            class_label = class_labels[value]
            where_clause = f"{field_delimiter} = {_sql_literal(value, field_type)}"
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
                query_features, seed_features = _select_feature_embedding_queries(
                    embedding_features, target_features, class_samples,
                    scratch_workspace, messages, class_label, feature_type == "Roads",
                )
                messages.addMessage(f"Finding matches for class '{class_label}' ({index} of {len(class_values)})...")
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


def _classify_target_features(
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
                coverage_percent = min(
                    100.0, (evidence_area / target_area) * 100.0
                ) if target_area else 0.0
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
            evidence_metric = "AreaCoveragePercent"
            cursor.updateRow([
                target_id, target_area, class_value, coverage_percent,
                class_reason, evidence_metric,
            ])
    arcpy.management.DeleteField(output_features, [target_id_field, target_area_field])
    messages.addMessage(
        f"Classified {classified_count} of {int(arcpy.management.GetCount(output_features)[0])} target feature(s)."
    )


def _sql_literal(value, field_type):
    if field_type in ("SmallInteger", "Integer", "Single", "Double"):
        return str(value)
    return "'{}'".format(str(value).replace("'", "''"))


def _class_value_label(feature_class, field_name, value):
    field = next(
        (candidate for candidate in arcpy.ListFields(feature_class) if candidate.name == field_name),
        None,
    )
    if not field or not field.domain:
        return str(value)
    workspace = _geodatabase_workspace(_dataset_label(feature_class))
    if not workspace:
        return str(value)
    try:
        domain = next(
            (candidate for candidate in arcpy.da.ListDomains(workspace) if candidate.name == field.domain),
            None,
        )
        descriptions = getattr(domain, "codedValues", {}) if domain else {}
        description = descriptions.get(value)
        if description is None:
            description = next(
                (
                    candidate_description
                    for code, candidate_description in descriptions.items()
                    if str(code) == str(value)
                ),
                None,
            )
        return f"{value} ({description})" if description else str(value)
    except Exception:
        return str(value)


class AutomatedDamageAssessment(object):
    FEATURE_TYPE = 0
    WORKFLOW = 1
    IN_TARGET = 2
    AOI = 3
    PRE_SOURCE = 4
    PRE_IMAGE = 5
    PRE_WAYBACK = 6
    SAM_MODEL = 7
    CUSTOM_PROMPT = 8
    DETECTION_CELL_SIZE = 9
    POST_SOURCE = 10
    POST_IMAGE = 11
    POST_WAYBACK = 12
    SAMPLE_POINTS = 13
    ONLINE_EMBEDDING_MODEL = 14
    EMBEDDING_MODEL = 15
    GPU_ID = 16
    BATCH_SIZE = 17
    GRID_SIZE = 18
    SIMILARITY_THRESHOLD = 19
    OUT_CLASSIFIED = 20
    MODERATE_THRESHOLD = 21
    HIGH_THRESHOLD = 22
    OUT_TARGET = 23
    OUT_EMBEDDINGS = 24
    OUT_SIMILAR = 25
    KEEP_INTERMEDIATE = 26
    EXISTING_EMBEDDINGS = 27

    def __init__(self):
        self.label = "Automated Damage Assessment"
        self.description = (
            "Extracts target features, finds post-event imagery features similar to "
            "user-marked examples, or assesses damage by comparing pre-event targets "
            "with post-event similarity results."
        )
        self.canRunInBackground = False
        self.environments = ["extent"]
        self._last_feature_type = None
        self._last_wayback_filter_key = None
        self._filtered_wayback_releases = None

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
        feature_type.filter.list = _feature_type_choices()
        feature_type.value = "Buildings"
        feature_type.category = "1. Target Features"

        workflow = arcpy.Parameter(
            displayName="Workflow",
            name="workflow",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        workflow.filter.type = "ValueList"
        workflow.filter.list = [
            "Feature Extraction",
            "Embedding Similarity",
            "Damage Assessment",
        ]
        workflow.value = "Damage Assessment"
        workflow.category = "1. Target Features"

        aoi = arcpy.Parameter(
            displayName=(
                "Area of Interest Polygon (Optional; Clips Supplied Targets and "
                "Overrides Extent)"
            ),
            name="in_aoi",
            datatype="GPFeatureLayer",
            parameterType="Optional",
            direction="Input",
        )
        aoi.filter.list = ["Polygon"]
        aoi.category = "1. Target Features"

        pre_source = arcpy.Parameter(
            displayName="Feature Extraction Imagery Source",
            name="pre_event_source",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        pre_source.filter.type = "ValueList"
        pre_source.filter.list = ["Input Imagery", "World Imagery Wayback"]
        pre_source.value = "Input Imagery"
        pre_source.category = "2. Feature Extraction"

        pre_image = arcpy.Parameter(
            displayName="Feature Extraction Imagery Layer (from Active Map)",
            name="in_pre_event_imagery",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        pre_image.filter.type = "ValueList"
        pre_image.filter.list = _get_active_map_raster_layer_names()
        pre_image.category = "2. Feature Extraction"

        pre_wayback = arcpy.Parameter(
            displayName="Feature Extraction World Imagery Wayback Release",
            name="pre_event_wayback_release",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        pre_wayback.filter.type = "ValueList"
        pre_wayback.filter.list = []
        pre_wayback.category = "2. Feature Extraction"

        sam_model = arcpy.Parameter(
            displayName="Custom Extraction Model (.dlpk, Optional; Default: Living Atlas SAM3)",
            name="in_sam_model",
            datatype="DEFile",
            parameterType="Optional",
            direction="Input",
        )
        sam_model.filter.list = ["dlpk"]
        sam_model.category = "2. Feature Extraction"

        custom_prompt = arcpy.Parameter(
            displayName="Custom SAM3 Text Prompt",
            name="custom_sam_prompt",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        custom_prompt.category = "2. Feature Extraction"

        detection_cell_size = arcpy.Parameter(
            displayName="Feature Detection Cell Size",
            name="detection_cell_size",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
        )
        detection_cell_size.value = FEATURE_PROFILES["Buildings"]["detection_cell_size"]
        detection_cell_size.category = "2. Feature Extraction"

        post_source = arcpy.Parameter(
            displayName="Post-Event Imagery Source",
            name="post_event_source",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        post_source.filter.type = "ValueList"
        post_source.filter.list = [
            "Input Imagery",
            "Current World Imagery",
            "World Imagery Wayback",
        ]
        post_source.value = "Input Imagery"
        post_source.category = "3. Post-Event Similarity"

        post_image = arcpy.Parameter(
            displayName="Post-Event Imagery Layer (from Active Map)",
            name="in_post_event_imagery",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        post_image.filter.type = "ValueList"
        post_image.filter.list = _get_active_map_raster_layer_names()
        post_image.category = "3. Post-Event Similarity"

        post_wayback = arcpy.Parameter(
            displayName="Post-Event World Imagery Wayback Release",
            name="post_event_wayback_release",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        post_wayback.filter.type = "ValueList"
        post_wayback.filter.list = []
        post_wayback.category = "3. Post-Event Similarity"

        sample_points = arcpy.Parameter(
            displayName="Example Points for Similarity Search (Minimum 6)",
            name="in_damage_sample_points",
            datatype="GPFeatureLayer",
            parameterType="Optional",
            direction="Input",
        )
        sample_points.filter.list = ["Point", "Multipoint"]
        sample_points.category = "3. Post-Event Similarity"

        online_embedding_model = arcpy.Parameter(
            displayName="ArcGIS Online Embedding Model",
            name="online_embedding_model",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        online_embedding_model.filter.type = "ValueList"
        online_embedding_model.filter.list = list(EMBEDDING_MODELS)
        online_embedding_model.value = next(iter(EMBEDDING_MODELS))
        online_embedding_model.category = "3. Post-Event Similarity"

        embedding_model = arcpy.Parameter(
            displayName="Custom Embedding Model (.dlpk, Optional Override)",
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
        batch_size.value = 4
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
            displayName="Output Features",
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

        existing_embeddings = arcpy.Parameter(
            displayName="Existing Post-Event Embeddings (Optional; Skips Generation)",
            name="in_existing_embeddings",
            datatype="GPFeatureLayer",
            parameterType="Optional",
            direction="Input",
        )
        existing_embeddings.filter.list = ["Polygon"]
        existing_embeddings.category = "3. Post-Event Similarity"

        return [
            feature_type,
            workflow,
            in_target,
            aoi,
            pre_source,
            pre_image,
            pre_wayback,
            sam_model,
            custom_prompt,
            detection_cell_size,
            post_source,
            post_image,
            post_wayback,
            sample_points,
            online_embedding_model,
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
            existing_embeddings,
        ]

    def updateParameters(self, parameters):
        feature_type = parameters[self.FEATURE_TYPE].valueAsText or "Buildings"
        workflow_options = FEATURE_WORKFLOWS.get(
            feature_type,
            ("Damage Assessment",),
        )
        workflow = parameters[self.WORKFLOW].valueAsText
        parameters[self.WORKFLOW].filter.list = list(workflow_options)
        parameters[self.WORKFLOW].enabled = feature_type in ("Debris", "Custom")
        if feature_type != self._last_feature_type:
            profile = FEATURE_PROFILES[feature_type]
            parameters[self.DETECTION_CELL_SIZE].value = profile["detection_cell_size"]
            self._last_feature_type = feature_type
        if workflow not in workflow_options:
            workflow = DEFAULT_WORKFLOWS.get(feature_type, workflow_options[0])
            parameters[self.WORKFLOW].value = workflow
        requires_extraction = workflow in ("Feature Extraction", "Damage Assessment")
        requires_similarity = workflow in ("Embedding Similarity", "Damage Assessment")
        has_target_features = (
            workflow == "Damage Assessment"
            and bool(parameters[self.IN_TARGET].valueAsText)
        )
        extracts_targets_from_post_event = (
            workflow == "Damage Assessment"
            and feature_type == "Vehicles"
            and not has_target_features
        )
        requires_pre_event_extraction = (
            requires_extraction and not extracts_targets_from_post_event
        )
        has_existing_embeddings = bool(
            parameters[self.EXISTING_EMBEDDINGS].valueAsText
        )
        parameters[self.AOI].enabled = True
        parameters[self.IN_TARGET].enabled = workflow == "Damage Assessment"
        parameters[self.EXISTING_EMBEDDINGS].enabled = requires_similarity
        for index in (
            self.PRE_SOURCE,
            self.PRE_IMAGE,
            self.PRE_WAYBACK,
        ):
            parameters[index].enabled = requires_pre_event_extraction and not has_target_features
        for index in (
            self.SAM_MODEL,
            self.CUSTOM_PROMPT,
            self.DETECTION_CELL_SIZE,
        ):
            parameters[index].enabled = requires_extraction and not has_target_features

        pre_source = parameters[self.PRE_SOURCE].valueAsText or "Input Imagery"
        if requires_pre_event_extraction and not has_target_features:
            parameters[self.PRE_IMAGE].enabled = pre_source == "Input Imagery"
            parameters[self.PRE_WAYBACK].enabled = pre_source == "World Imagery Wayback"

        post_source = parameters[self.POST_SOURCE].valueAsText or "Input Imagery"
        for index in (
            self.POST_SOURCE,
            self.ONLINE_EMBEDDING_MODEL,
            self.EMBEDDING_MODEL,
            self.GPU_ID,
            self.BATCH_SIZE,
            self.GRID_SIZE,
        ):
            parameters[index].enabled = requires_similarity and not has_existing_embeddings
        parameters[self.POST_IMAGE].enabled = (
            requires_similarity
            and not has_existing_embeddings
            and post_source == "Input Imagery"
        )
        parameters[self.POST_WAYBACK].enabled = (
            requires_similarity
            and not has_existing_embeddings
            and post_source == "World Imagery Wayback"
        )
        parameters[self.SAMPLE_POINTS].enabled = requires_similarity
        parameters[self.SIMILARITY_THRESHOLD].enabled = requires_similarity
        for index in (self.MODERATE_THRESHOLD, self.HIGH_THRESHOLD):
            parameters[index].enabled = workflow == "Damage Assessment"

        raster_layer_names = _get_active_map_raster_layer_names()
        parameters[self.PRE_IMAGE].filter.list = raster_layer_names
        parameters[self.POST_IMAGE].filter.list = raster_layer_names

        uses_wayback = (
            (
                requires_pre_event_extraction
                and not has_target_features
                and pre_source == "World Imagery Wayback"
            )
            or (
                requires_similarity
                and
                not has_existing_embeddings
                and post_source == "World Imagery Wayback"
            )
        )
        if uses_wayback:
            filter_extent = _get_wayback_filter_extent(
                parameters[self.AOI].valueAsText,
                parameters[self.IN_TARGET].valueAsText,
            )
            filter_key = _wayback_filter_key(filter_extent)
            if filter_key != self._last_wayback_filter_key:
                self._last_wayback_filter_key = filter_key
                try:
                    self._filtered_wayback_releases = (
                        _get_wayback_releases_with_local_changes(*filter_extent)
                        if filter_extent
                        else None
                    )
                except Exception:
                    self._filtered_wayback_releases = None
            releases = (
                self._filtered_wayback_releases
                if self._filtered_wayback_releases is not None
                else _get_wayback_releases()
            )
            parameters[self.PRE_WAYBACK].filter.list = [
                release[0] for release in releases
            ]
            post_releases = releases
            pre_wayback_release = parameters[self.PRE_WAYBACK].valueAsText
            if (
                not has_target_features
                and pre_source == "World Imagery Wayback"
                and pre_wayback_release
            ):
                selected_pre_release = next(
                    (
                        release
                        for release in releases
                        if release[0] == pre_wayback_release
                    ),
                    None,
                )
                if selected_pre_release:
                    post_releases = [
                        release
                        for release in releases
                        if release[1] > selected_pre_release[1]
                    ]
            post_wayback_choices = [release[0] for release in post_releases]
            parameters[self.POST_WAYBACK].filter.list = post_wayback_choices
            if (
                parameters[self.POST_WAYBACK].valueAsText
                and parameters[self.POST_WAYBACK].valueAsText
                not in post_wayback_choices
            ):
                parameters[self.POST_WAYBACK].value = None

        parameters[self.CUSTOM_PROMPT].enabled = (
            requires_extraction
            and not has_target_features
            and feature_type == "Custom"
        )
        return

    def updateMessages(self, parameters):
        workflow = parameters[self.WORKFLOW].valueAsText or "Damage Assessment"
        requires_extraction = workflow in ("Feature Extraction", "Damage Assessment")
        requires_similarity = workflow in ("Embedding Similarity", "Damage Assessment")
        has_target_features = (
            workflow == "Damage Assessment"
            and bool(parameters[self.IN_TARGET].valueAsText)
        )
        extracts_targets_from_post_event = (
            workflow == "Damage Assessment"
            and parameters[self.FEATURE_TYPE].valueAsText == "Vehicles"
            and not has_target_features
        )
        requires_pre_event_extraction = (
            requires_extraction and not extracts_targets_from_post_event
        )
        existing_embeddings = parameters[self.EXISTING_EMBEDDINGS].valueAsText
        if requires_pre_event_extraction and not has_target_features:
            pre_source = parameters[self.PRE_SOURCE].valueAsText

        post_source = parameters[self.POST_SOURCE].valueAsText or "Input Imagery"
        if extracts_targets_from_post_event and post_source != "Input Imagery":
            parameters[self.POST_SOURCE].setErrorMessage(
                "Vehicle damage assessment requires an input post-event imagery layer "
                "for vehicle extraction."
            )
        if (
            requires_similarity
            and not existing_embeddings
            and post_source == "World Imagery Wayback"
            and not parameters[self.POST_WAYBACK].valueAsText
        ):
            pre_wayback_selected = (
                requires_pre_event_extraction
                and
                not has_target_features
                and pre_source == "World Imagery Wayback"
                and parameters[self.PRE_WAYBACK].valueAsText
            )
            if pre_wayback_selected and not parameters[self.POST_WAYBACK].filter.list:
                parameters[self.POST_WAYBACK].setErrorMessage(
                    "No local Wayback release is available after the selected "
                    "pre-event release. Choose an earlier pre-event release or use "
                    "input post-event imagery."
                )

        if self._filtered_wayback_releases:
            filter_message = (
                f"Filtered to {len(self._filtered_wayback_releases)} Wayback "
                "release(s) with local imagery changes at the analysis-area center."
            )
            if (
                requires_extraction
                and
                not has_target_features
                and pre_source == "World Imagery Wayback"
                and parameters[self.PRE_WAYBACK].valueAsText
            ):
                parameters[self.PRE_WAYBACK].setWarningMessage(filter_message)
            if (
                post_source == "World Imagery Wayback"
                and parameters[self.POST_WAYBACK].valueAsText
            ):
                parameters[self.POST_WAYBACK].setWarningMessage(filter_message)

        if requires_extraction and not has_target_features:
            _set_positive_error(
                parameters[self.DETECTION_CELL_SIZE], "Detection cell size"
            )
        grid_size = parameters[self.GRID_SIZE].value
        if (
            requires_similarity
            and not existing_embeddings
            and grid_size is not None
            and int(grid_size) < 1
        ):
            parameters[self.GRID_SIZE].setErrorMessage(
                "Grid size must be a positive integer or left blank for Auto."
            )

        similarity = parameters[self.SIMILARITY_THRESHOLD].value
        if requires_similarity and similarity is not None and not 0 < float(similarity) <= 1:
            parameters[self.SIMILARITY_THRESHOLD].setErrorMessage(
                "Similarity threshold must be greater than 0 and at most 1."
            )

        batch_size = parameters[self.BATCH_SIZE].value
        if (
            requires_similarity
            and not existing_embeddings
            and batch_size is not None
            and int(batch_size) < 1
        ):
            parameters[self.BATCH_SIZE].setErrorMessage("Batch size must be at least 1.")
        elif (
            requires_similarity
            and not existing_embeddings
            and batch_size is not None
            and int(batch_size) > 8
        ):
            parameters[self.BATCH_SIZE].setWarningMessage(
                "Batch sizes above 8 can exhaust GPU memory; start with 4."
            )

        if requires_similarity and existing_embeddings and not _has_embedding_field(existing_embeddings):
            parameters[self.EXISTING_EMBEDDINGS].setErrorMessage(
                "Existing post-event embeddings must contain a BLOB embedding field."
            )

        sample_parameter = parameters[self.SAMPLE_POINTS]
        if requires_similarity and sample_parameter.value:
            try:
                sample_count = int(
                    arcpy.management.GetCount(sample_parameter.value)[0]
                )
            except Exception:
                try:
                    sample_count = int(
                        arcpy.management.GetCount(sample_parameter.valueAsText)[0]
                    )
                except Exception:
                    sample_count = None
            if sample_count is not None and sample_count < 6:
                sample_parameter.setErrorMessage(
                    "Provide at least 6 damage example point features; "
                    f"the selected layer contains {sample_count}."
                )

        if workflow == "Damage Assessment":
            _validate_coverage_parameters(
                parameters[self.MODERATE_THRESHOLD], parameters[self.HIGH_THRESHOLD]
            )
        output_path = parameters[self.OUT_CLASSIFIED].valueAsText
        if output_path and (
            _same_dataset(output_path, parameters[self.IN_TARGET].valueAsText)
            or _same_dataset(output_path, existing_embeddings)
        ):
            parameters[self.OUT_CLASSIFIED].setErrorMessage(
                "Output Features must differ from target features and existing "
                "post-event embeddings."
            )
        elif output_path and not _geodatabase_workspace(output_path):
            parameters[self.OUT_CLASSIFIED].setErrorMessage(
                "Output must be stored in a file or enterprise geodatabase because "
                "embedding feature classes contain a BLOB field."
            )
        elif (
            output_path
            and arcpy.Exists(output_path)
        ):
            parameters[self.OUT_CLASSIFIED].setWarningMessage(
                "The existing output will be replaced after similarity "
                "analysis succeeds."
            )
        return

    def execute(self, parameters, messages):
        workflow = parameters[self.WORKFLOW].valueAsText or "Damage Assessment"
        feature_type = parameters[self.FEATURE_TYPE].valueAsText
        allowed_workflows = FEATURE_WORKFLOWS.get(
            feature_type,
            ("Damage Assessment",),
        )
        if workflow not in allowed_workflows:
            raise arcpy.ExecuteError(
                f"{workflow} is not available for {feature_type}. Choose one of: "
                f"{', '.join(allowed_workflows)}."
            )
        requires_extraction = workflow in ("Feature Extraction", "Damage Assessment")
        requires_similarity = workflow in ("Embedding Similarity", "Damage Assessment")
        in_target = parameters[self.IN_TARGET].valueAsText
        extracts_targets_from_post_event = (
            workflow == "Damage Assessment"
            and feature_type == "Vehicles"
            and not in_target
        )
        requires_pre_event_extraction = (
            requires_extraction and not extracts_targets_from_post_event
        )
        aoi = parameters[self.AOI].valueAsText
        pre_source = parameters[self.PRE_SOURCE].valueAsText or "Input Imagery"
        pre_image = None
        if requires_pre_event_extraction and pre_source == "Input Imagery":
            pre_image = _resolve_active_map_raster_layer(
                parameters[self.PRE_IMAGE].valueAsText
            )
        pre_wayback_release = parameters[self.PRE_WAYBACK].valueAsText
        sam_model = parameters[self.SAM_MODEL].valueAsText
        custom_prompt = parameters[self.CUSTOM_PROMPT].valueAsText
        existing_embeddings = parameters[self.EXISTING_EMBEDDINGS].valueAsText
        post_source = parameters[self.POST_SOURCE].valueAsText or "Input Imagery"
        if extracts_targets_from_post_event and post_source != "Input Imagery":
            raise arcpy.ExecuteError(
                "Vehicle damage assessment requires an input post-event imagery layer "
                "for vehicle extraction."
            )
        post_image = None
        if (
            requires_similarity
            and not existing_embeddings
            and post_source == "Input Imagery"
        ):
            post_image = _resolve_active_map_raster_layer(
                parameters[self.POST_IMAGE].valueAsText
            )
        sample_points = parameters[self.SAMPLE_POINTS].valueAsText
        online_embedding_model = parameters[self.ONLINE_EMBEDDING_MODEL].valueAsText
        embedding_model = parameters[self.EMBEDDING_MODEL].valueAsText
        gpu_id = int(parameters[self.GPU_ID].value or 0)
        batch_size = int(parameters[self.BATCH_SIZE].value or 4)
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
                "Output Features must be stored in a file or "
                "enterprise geodatabase."
            )
        if _same_dataset(out_classified, in_target) or _same_dataset(
            out_classified, existing_embeddings
        ):
            raise arcpy.ExecuteError(
                "Output Features must differ from target features and existing "
                "post-event embeddings."
            )
        scratch_workspace = arcpy.env.scratchGDB
        messages.addMessage(f"Automated Damage Assessment version {TOOL_VERSION}")
        messages.addMessage(f"Feature type: {feature_type}")
        if requires_extraction or (requires_similarity and not existing_embeddings):
            _validate_gpu_memory(gpu_id, messages)

        target_features = in_target if workflow == "Damage Assessment" else None
        generated_target_features = None
        generated_embeddings = None
        out_embeddings = None
        out_similar = None
        generated_wayback_rasters = []
        post_event_cache = None
        pre_wayback_metadata = None
        post_wayback_metadata = None
        if requires_extraction and target_features:
            messages.addMessage("Using user-supplied target features; pre-event extraction is skipped.")
            analysis_extent, analysis_spatial_reference, extent_source = (
                _resolve_analysis_extent(aoi, target_features, False)
            )
            if aoi:
                target_features = _clip_targets_to_aoi(
                    target_features,
                    aoi,
                    feature_type,
                    output_workspace,
                    messages,
                )
                generated_target_features = target_features
        elif requires_extraction:
            detection_cell_size = float(
                parameters[self.DETECTION_CELL_SIZE].value
                or FEATURE_PROFILES[feature_type]["detection_cell_size"]
            )
            source_imagery = post_image if extracts_targets_from_post_event else pre_image
            if extracts_targets_from_post_event:
                source_imagery = _ensure_web_mercator_raster(
                    source_imagery, "Post-event imagery", messages
                )
                analysis_extent, analysis_spatial_reference, extent_source = (
                    _resolve_analysis_extent(aoi, source_imagery, True)
                )
                post_image = source_imagery
            elif pre_source == "World Imagery Wayback":
                analysis_extent, analysis_spatial_reference, extent_source = (
                    _resolve_analysis_extent(aoi, None, True)
                )
            else:
                source_imagery = _ensure_web_mercator_raster(
                    source_imagery, "Pre-event imagery", messages
                )
                analysis_extent, analysis_spatial_reference, extent_source = (
                    _resolve_analysis_extent(aoi, source_imagery, True)
                )
            if not extracts_targets_from_post_event and pre_source == "World Imagery Wayback":
                pre_wayback_metadata = _validate_wayback_coverage(
                    pre_wayback_release,
                    analysis_extent,
                    analysis_spatial_reference,
                    "Pre-event",
                    messages,
                )
                source_imagery = _materialize_wayback_imagery(
                    pre_wayback_release,
                    analysis_extent,
                    analysis_spatial_reference,
                    _wayback_cell_size(
                        pre_wayback_metadata, detection_cell_size
                    ),
                    "PreEvent",
                    messages,
                )
                generated_wayback_rasters.append(source_imagery)
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

        if workflow == "Feature Extraction":
            if arcpy.Exists(out_classified):
                messages.addMessage("Replacing the existing extracted feature output...")
                arcpy.management.Delete(out_classified)
            arcpy.management.CopyFeatures(target_features, out_classified)
            parameters[self.OUT_TARGET].value = out_classified
            parameters[self.OUT_CLASSIFIED].value = out_classified
            if not keep_intermediate:
                for dataset in (generated_target_features, *generated_wayback_rasters):
                    if dataset and arcpy.Exists(dataset):
                        arcpy.management.Delete(dataset)
            return

        if not requires_extraction:
            if existing_embeddings:
                analysis_extent = None
                analysis_spatial_reference = None
                extent_source = "Existing post-event embeddings"
            elif post_source == "World Imagery Wayback":
                analysis_extent, analysis_spatial_reference, extent_source = (
                    _resolve_analysis_extent(aoi, None, True)
                )
            else:
                post_image = _ensure_web_mercator_raster(
                    post_image, "Post-event imagery", messages
                )
                analysis_extent, analysis_spatial_reference, extent_source = (
                    _resolve_analysis_extent(aoi, post_image, True)
                )

        if requires_similarity and not existing_embeddings:
            (
                post_image,
                post_event_cache,
                post_wayback_metadata,
            ) = _resolve_post_event_imagery(
                post_source,
                post_image,
                parameters[self.POST_WAYBACK].valueAsText,
                analysis_extent,
                analysis_spatial_reference,
                messages,
            )

        messages.addMessage(f"Analysis extent source: {extent_source}")
        if (
            pre_wayback_metadata
            and post_wayback_metadata
            and pre_wayback_metadata == post_wayback_metadata
        ):
            messages.addWarningMessage(
                "The selected pre-event and post-event Wayback releases use the same "
                "local imagery over the analysis area. Choose another release if you "
                "need imagery from a different acquisition."
            )
        if target_features:
            parameters[self.OUT_TARGET].value = target_features
        query_features = None
        if workflow == "Damage Assessment":
            query_features = _select_damage_queries(
                target_features,
                sample_points,
                feature_type,
                scratch_workspace,
                messages,
            )
        run_succeeded = False

        try:
            if existing_embeddings:
                if not _has_embedding_field(existing_embeddings):
                    raise arcpy.ExecuteError(
                        "Existing post-event embeddings must contain a BLOB "
                        "embedding field."
                    )
                out_embeddings = existing_embeddings
                messages.addMessage(
                    "Using existing post-event embeddings; imagery preparation and "
                    "embedding generation are skipped."
                )
            else:
                grid_size = requested_grid_size or _recommend_grid_size(
                    target_features or sample_points,
                    post_image,
                    feature_type,
                )
                grid_source = (
                    "user supplied" if requested_grid_size else "Auto recommendation"
                )
                messages.addMessage(
                    f"Embedding grid size: {grid_size} ({grid_source})"
                )
                selected_model = EMBEDDING_MODELS[online_embedding_model]
                embedding_model = _resolve_model(
                    embedding_model,
                    selected_model["item_id"],
                    selected_model["file_name"],
                    messages,
                )
                output_spatial_reference = arcpy.Describe(
                    target_features or post_image
                ).spatialReference
                if post_event_cache is None:
                    post_image, post_event_cache = _materialize_image_service_if_needed(
                        post_image,
                        analysis_extent,
                        analysis_spatial_reference,
                        embedding_model,
                        grid_size,
                        batch_size,
                        output_spatial_reference,
                        messages,
                    )
                post_image = _ensure_web_mercator_raster(
                    post_image, "Post-event imagery", messages
                )
                out_embeddings = arcpy.CreateUniqueName(
                    "Damage_PostEvent_Embeddings", output_workspace
                )
                generated_embeddings = out_embeddings
                _generate_embeddings(
                    post_image,
                    out_embeddings,
                    embedding_model,
                    batch_size,
                    grid_size,
                    gpu_id,
                    analysis_extent,
                    analysis_spatial_reference,
                    output_spatial_reference,
                    post_event_cache,
                    messages,
                )
            parameters[self.OUT_EMBEDDINGS].value = out_embeddings

            if workflow == "Embedding Similarity":
                query_features = _select_embedding_queries(
                    out_embeddings, sample_points, scratch_workspace, messages
                )

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

            if arcpy.Exists(out_classified):
                messages.addMessage("Replacing the existing output...")
                arcpy.management.Delete(out_classified)

            if workflow == "Damage Assessment":
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
            elif feature_type == "Debris":
                _create_debris_clusters(
                    out_similar,
                    out_classified,
                    scratch_workspace,
                    messages,
                )
            else:
                arcpy.management.CopyFeatures(out_similar, out_classified)
            parameters[self.OUT_CLASSIFIED].value = out_classified
            run_succeeded = True
        finally:
            if query_features and arcpy.Exists(query_features):
                arcpy.management.Delete(query_features)
            if post_event_cache and run_succeeded:
                _delete_image_service_cache(post_event_cache["cache_root"])
            elif post_event_cache:
                messages.addWarningMessage(
                    "Retained resumable processing cache: "
                    f"{post_event_cache['cache_root']}"
                )
            if not keep_intermediate:
                messages.addMessage("Deleting generated intermediate data...")
                for dataset in (
                    out_similar,
                    generated_embeddings,
                    generated_target_features,
                    *generated_wayback_rasters,
                ):
                    if dataset and arcpy.Exists(dataset):
                        arcpy.management.Delete(dataset)
                    tile_folder = f"{os.path.splitext(dataset)[0]}_tiles" if dataset else None
                    if tile_folder and os.path.isdir(tile_folder):
                        shutil.rmtree(tile_folder, ignore_errors=True)
                parameters[self.OUT_TARGET].value = None
                if generated_embeddings:
                    parameters[self.OUT_EMBEDDINGS].value = None
                parameters[self.OUT_SIMILAR].value = None


def _validate_gpu_memory(gpu_id, messages):
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                f"--id={gpu_id}",
                "--query-gpu=memory.free,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=10,
        )
        free_memory, total_memory = (
            int(value.strip()) for value in result.stdout.splitlines()[0].split(",")
        )
    except (FileNotFoundError, subprocess.SubprocessError, ValueError, IndexError) as error:
        messages.addWarningMessage(
            "Could not check GPU memory with nvidia-smi; deep-learning tools will "
            f"perform their own GPU validation. Details: {error}"
        )
        return

    messages.addMessage(
        f"GPU {gpu_id} memory available: {free_memory:,} MiB of {total_memory:,} MiB."
    )
    if free_memory < 1024:
        raise arcpy.ExecuteError(
            f"GPU {gpu_id} has only {free_memory:,} MiB free. SAM3 cannot initialize "
            "with less than 1,024 MiB available. Close GPU-heavy applications or "
            "restart ArcGIS Pro, then run the tool again."
        )
    if free_memory < 6144:
        messages.addWarningMessage(
            f"GPU {gpu_id} has only {free_memory:,} MiB free. SAM3 may run out of "
            "memory; close GPU-heavy applications and use batch size 4 or lower."
        )


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
        if (
            (not spatial_reference or getattr(spatial_reference, "name", "Unknown") == "Unknown")
            and fallback_dataset
        ):
            spatial_reference = arcpy.Describe(fallback_dataset).spatialReference
        if not spatial_reference or getattr(spatial_reference, "name", "Unknown") == "Unknown":
            raise arcpy.ExecuteError(
                "The Extent environment must have a defined coordinate system when "
                "World Imagery Wayback is used. Use an AOI polygon or an extent from "
                "a map layer with a defined coordinate system."
            )
        return environment_extent, spatial_reference, "Extent environment"

    if require_explicit_extent:
        raise arcpy.ExecuteError(
            "Provide an Area of Interest polygon or set the Extent environment."
        )

    description = arcpy.Describe(fallback_dataset)
    return description.extent, description.spatialReference, "input target features"


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


def _materialize_image_service_if_needed(
    raster,
    analysis_extent,
    analysis_spatial_reference,
    model,
    grid_size,
    batch_size,
    output_spatial_reference,
    messages,
):
    service_url = _image_service_url(raster)
    if not service_url:
        return raster, None

    source_spatial_reference, cell_width, cell_height = (
        _image_service_raster_properties(raster, service_url, messages)
    )

    source_extent = _project_extent(
        analysis_extent,
        analysis_spatial_reference,
        source_spatial_reference,
    )
    column_count = math.ceil(source_extent.width / cell_width)
    row_count = math.ceil(source_extent.height / cell_height)
    if (
        column_count <= IMAGE_SERVICE_TILE_SIZE
        and row_count <= IMAGE_SERVICE_TILE_SIZE
    ):
        return raster, None

    tile_columns = math.ceil(column_count / IMAGE_SERVICE_TILE_SIZE)
    tile_rows = math.ceil(row_count / IMAGE_SERVICE_TILE_SIZE)
    tile_count = tile_columns * tile_rows
    if tile_count > MAX_WAYBACK_TILES:
        raise arcpy.ExecuteError(
            f"The post-event image service requires {tile_count:,} local tiles at "
            "native resolution. Reduce the Extent environment before running the tool."
        )

    cache_root = _image_service_cache_root(
        raster,
        service_url,
        source_extent,
        source_spatial_reference,
        cell_width,
        cell_height,
    )
    tile_folder = os.path.join(cache_root, "tiles")
    os.makedirs(tile_folder, exist_ok=True)
    messages.addMessage(f"Resumable processing cache: {cache_root}")
    messages.addMessage(
        f"Post-event image service request is {column_count:,} by {row_count:,} "
        f"pixels, above the {IMAGE_SERVICE_TILE_SIZE:,}-pixel safe request size."
    )

    try:
        tile_span_x = IMAGE_SERVICE_TILE_SIZE * cell_width
        tile_span_y = IMAGE_SERVICE_TILE_SIZE * cell_height
        tile_records = []
        for row in range(tile_rows):
            tile_ymax = source_extent.YMax - row * tile_span_y
            tile_ymin = max(source_extent.YMin, tile_ymax - tile_span_y)
            for column in range(tile_columns):
                tile_xmin = source_extent.XMin + column * tile_span_x
                tile_xmax = min(source_extent.XMax, tile_xmin + tile_span_x)
                tile_path = os.path.join(
                    tile_folder, f"post_event_{row}_{column}.tif"
                )
                tile_records.append(
                    (
                        tile_path,
                        tile_xmin,
                        tile_ymin,
                        tile_xmax,
                        tile_ymax,
                    )
                )

        cache = {
            "cache_root": cache_root,
            "tile_records": tuple(tile_records),
            "source_extent": source_extent,
            "spatial_reference": source_spatial_reference,
            "cell_width": cell_width,
            "cell_height": cell_height,
        }
        chunk_count = len(
            _embedding_chunk_extents(
                cache,
                analysis_extent,
                analysis_spatial_reference,
                grid_size,
            )
        )
        chunk_workspace = _embedding_checkpoint_workspace(
            cache_root,
            model,
            grid_size,
            batch_size,
            output_spatial_reference,
        )
        messages.addMessage(
            f"Checking {chunk_count:,} embedding completion markers..."
        )
        if all(
            _valid_embedding_checkpoint(
                os.path.join(
                    chunk_workspace, f"EmbeddingChunk_{index:04d}"
                )
            )
            for index in range(1, chunk_count + 1)
        ):
            messages.addMessage(
                f"Found all {chunk_count:,} completed embedding checkpoints; "
                "skipping image-tile cache validation."
            )
            cache["embedding_checkpoints_prevalidated"] = True
            return raster, cache

        messages.addMessage(
            f"Caching {tile_count:,} tiles locally at native resolution..."
        )
        reused_tile_count = 0
        for tile_path, tile_xmin, tile_ymin, tile_xmax, tile_ymax in tile_records:
            if _valid_cached_raster(tile_path):
                reused_tile_count += 1
                continue
            _delete_cached_raster(tile_path)
            _delete_checkpoint_marker(tile_path)
            _export_image_service_tile(
                raster,
                tile_path,
                arcpy.Extent(
                    tile_xmin, tile_ymin, tile_xmax, tile_ymax
                ),
                source_spatial_reference,
                cell_width,
                messages,
            )
            _write_checkpoint_marker(tile_path)

        if reused_tile_count:
            messages.addMessage(
                f"Resumed image-service cache with {reused_tile_count:,} of "
                f"{tile_count:,} tiles already complete."
            )
        messages.addMessage(
            "Cached image-service tiles are ready for extent-based processing."
        )
        return raster, cache
    except Exception as error:
        raise arcpy.ExecuteError(
            "Could not complete the resumable post-event image cache. Run the tool "
            f"again to continue from {cache_root}. Details: {error}"
        )


def _export_image_service_tile(
    raster,
    tile_path,
    tile_extent,
    spatial_reference,
    cell_size,
    messages,
):
    last_error = None
    for attempt in range(1, 4):
        temporary_path = (
            f"{os.path.splitext(tile_path)[0]}.part_{uuid.uuid4().hex}.tif"
        )
        _delete_cached_raster(temporary_path)
        try:
            with arcpy.EnvManager(
                extent=tile_extent,
                outputCoordinateSystem=spatial_reference,
                cellSize=cell_size,
                compression="LZW",
            ):
                arcpy.management.Clip(
                    in_raster=raster,
                    rectangle=(
                        f"{tile_extent.XMin} {tile_extent.YMin} "
                        f"{tile_extent.XMax} {tile_extent.YMax}"
                    ),
                    out_raster=temporary_path,
                    in_template_dataset="#",
                    nodata_value="#",
                    clipping_geometry="NONE",
                    maintain_clipping_extent="NO_MAINTAIN_EXTENT",
                )
            if not _valid_raster_output(temporary_path):
                raise arcpy.ExecuteError(
                    "The temporary tile is incomplete or unreadable."
                )

            _delete_cached_raster(tile_path)
            os.replace(temporary_path, tile_path)
            if not _valid_raster_output(tile_path):
                raise arcpy.ExecuteError(
                    "The promoted tile is incomplete or unreadable."
                )
            _delete_cached_raster(temporary_path)
            return
        except Exception as error:
            last_error = error
            _delete_cached_raster(temporary_path)
            if not _valid_raster_output(tile_path):
                _delete_cached_raster(tile_path)
            if attempt < 3:
                messages.addWarningMessage(
                    f"Tile export attempt {attempt} failed for "
                    f"{os.path.basename(tile_path)}; retrying with a clean "
                    f"temporary raster. Details: {error}"
                )

    raise arcpy.ExecuteError(
        f"Tile export failed after 3 attempts: {tile_path}. Details: {last_error}"
    )


def _image_service_cache_root(
    raster,
    service_url,
    source_extent,
    spatial_reference,
    cell_width,
    cell_height,
):
    wkid = (
        getattr(spatial_reference, "factoryCode", 0)
        or getattr(spatial_reference, "latestWkid", 0)
        or spatial_reference.name
    )
    cache_key = json.dumps(
        {
            "cache_format": CACHE_FORMAT_VERSION,
            "service": service_url.lower(),
            "layer": _image_service_layer_signature(raster),
            "extent": [
                round(source_extent.XMin, 6),
                round(source_extent.YMin, 6),
                round(source_extent.XMax, 6),
                round(source_extent.YMax, 6),
            ],
            "wkid": wkid,
            "cell_size": [round(cell_width, 12), round(cell_height, 12)],
        },
        sort_keys=True,
    )
    cache_id = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:16]
    return os.path.join(
        arcpy.env.scratchFolder, f"DamageAssessment_{cache_id}"
    )


def _image_service_layer_signature(raster):
    signature = {
        "name": getattr(raster, "name", None),
        "data_source": getattr(raster, "dataSource", None),
        "definition_query": getattr(raster, "definitionQuery", None),
    }
    try:
        signature["connection_properties"] = raster.connectionProperties
    except Exception:
        pass
    return json.dumps(signature, sort_keys=True, default=str)


def _valid_cached_raster(raster_path):
    if (
        not os.path.isfile(_checkpoint_marker(raster_path))
        or not _valid_raster_output(raster_path)
    ):
        return False

    return True


def _valid_raster_output(raster_path):
    if not arcpy.Exists(raster_path):
        return False
    try:
        column_count = int(
            float(
                arcpy.management.GetRasterProperties(
                    raster_path, "COLUMNCOUNT"
                ).getOutput(0)
            )
        )
        row_count = int(
            float(
                arcpy.management.GetRasterProperties(
                    raster_path, "ROWCOUNT"
                ).getOutput(0)
            )
        )
        if column_count <= 0 or row_count <= 0:
            return False
        cached_raster = arcpy.Raster(raster_path)
        sample = arcpy.RasterToNumPyArray(cached_raster, ncols=1, nrows=1)
        return sample.size > 0
    except Exception:
        return False


def _checkpoint_marker(dataset_path):
    parent_workspace = os.path.dirname(dataset_path)
    if parent_workspace.lower().endswith(".gdb"):
        marker_folder = os.path.join(
            os.path.dirname(parent_workspace),
            f"{os.path.basename(parent_workspace)}_checkpoints",
        )
    else:
        marker_folder = os.path.join(parent_workspace, ".checkpoints")
    return os.path.join(
        marker_folder, f"{os.path.basename(dataset_path)}.complete"
    )


def _write_checkpoint_marker(dataset_path):
    marker_path = _checkpoint_marker(dataset_path)
    os.makedirs(os.path.dirname(marker_path), exist_ok=True)
    with open(marker_path, "w", encoding="ascii") as marker_file:
        marker_file.write("complete\n")


def _delete_checkpoint_marker(dataset_path):
    marker_path = _checkpoint_marker(dataset_path)
    if os.path.isfile(marker_path):
        os.remove(marker_path)


def _delete_image_service_cache(cache_root):
    try:
        arcpy.management.ClearWorkspaceCache()
    except Exception:
        pass
    shutil.rmtree(cache_root, ignore_errors=True)


def _generate_embeddings(
    raster,
    output_embeddings,
    model,
    batch_size,
    grid_size,
    gpu_id,
    analysis_extent,
    analysis_spatial_reference,
    output_spatial_reference,
    image_service_cache,
    messages,
):
    use_chunks = bool(image_service_cache)
    checkpoints_prevalidated = bool(
        image_service_cache
        and image_service_cache.get("embedding_checkpoints_prevalidated")
    )
    chunk_extents = (
        _embedding_chunk_extents(
            image_service_cache,
            analysis_extent,
            analysis_spatial_reference,
            grid_size,
        )
        if use_chunks
        else [analysis_extent]
    )
    chunk_count = len(chunk_extents)
    if not checkpoints_prevalidated:
        if chunk_count > 1:
            messages.addMessage(
                f"Generating embeddings in {chunk_count:,} bounded spatial chunks "
                "to avoid long-running raster worker timeouts."
            )
        else:
            messages.addMessage("Generating embeddings from analysis imagery...")

    chunk_workspace = None
    chunk_raster_folder = None
    if use_chunks:
        chunk_workspace = _embedding_checkpoint_workspace(
            image_service_cache["cache_root"],
            model,
            grid_size,
            batch_size,
            output_spatial_reference,
        )
        if not arcpy.Exists(chunk_workspace):
            arcpy.management.CreateFileGDB(
                os.path.dirname(chunk_workspace),
                os.path.basename(chunk_workspace),
            )
        chunk_raster_folder = os.path.join(
            image_service_cache["cache_root"],
            f"{os.path.splitext(os.path.basename(chunk_workspace))[0]}_rasters",
        )
        os.makedirs(chunk_raster_folder, exist_ok=True)

    chunk_outputs = []
    try:
        for index, chunk_extent in enumerate(chunk_extents, start=1):
            chunk_output = output_embeddings
            chunk_raster = None
            if use_chunks:
                chunk_output = os.path.join(
                    chunk_workspace, f"EmbeddingChunk_{index:04d}"
                )
                chunk_outputs.append(chunk_output)
                chunk_raster = os.path.join(
                    chunk_raster_folder, f"EmbeddingInput_{index:04d}.tif"
                )
                if checkpoints_prevalidated:
                    continue
                if _valid_embedding_checkpoint(chunk_output):
                    messages.addMessage(
                        f"Reusing completed embedding chunk {index:,} of "
                        f"{chunk_count:,}."
                    )
                    _delete_cached_raster(chunk_raster)
                    continue
                if arcpy.Exists(chunk_output):
                    arcpy.management.Delete(chunk_output)
                _delete_checkpoint_marker(chunk_output)
            if chunk_count > 1:
                messages.addMessage(
                    f"Generating embedding chunk {index:,} of {chunk_count:,}..."
                )

            embedding_input = raster
            environment = {
                "gpuId": gpu_id,
                "extent": chunk_extent,
                "processorType": "GPU",
                "outputCoordinateSystem": output_spatial_reference,
                "recycleProcessingWorkers": 1,
            }
            if use_chunks:
                embedding_input = _prepare_embedding_chunk_raster(
                    chunk_raster,
                    chunk_extent,
                    image_service_cache,
                )
                environment["cellSize"] = max(
                    image_service_cache["cell_width"],
                    image_service_cache["cell_height"],
                )
                environment["snapRaster"] = embedding_input

            try:
                with arcpy.EnvManager(**environment):
                    _generate_embeddings_with_model(
                        in_data=embedding_input,
                        out_embeddings_feature_class=chunk_output,
                        in_model_definition_file=model,
                        arguments=(
                            f"batch_size {batch_size};data_src RGB;"
                            "radiometric_offset_correction False;"
                            f"grid_size {grid_size}"
                        ),
                    )
            finally:
                _release_gpu_memory()
                if use_chunks:
                    del embedding_input
                    _delete_cached_raster(chunk_raster)
            if use_chunks:
                if not _valid_embedding_output(chunk_output):
                    raise arcpy.ExecuteError(
                        "Embedding generation did not create a valid checkpoint "
                        f"for chunk {index:,}."
                    )
                _write_checkpoint_marker(chunk_output)

        if use_chunks:
            if arcpy.Exists(output_embeddings):
                arcpy.management.Delete(output_embeddings)
            with arcpy.EnvManager(workspace=chunk_workspace):
                for staged_output in arcpy.ListFeatureClasses("EmbeddingMerge_*"):
                    staged_path = os.path.join(chunk_workspace, staged_output)
                    arcpy.management.Delete(staged_path)
                    _delete_checkpoint_marker(staged_path)
            messages.addMessage(
                f"Assembling {len(chunk_outputs):,} completed embedding chunks "
                "with one direct merge..."
            )
            _merge_embedding_chunks(
                chunk_outputs,
                output_embeddings,
            )
    except Exception:
        if arcpy.Exists(output_embeddings):
            arcpy.management.Delete(output_embeddings)
        raise


def _generate_embeddings_with_model(**kwargs):
    generate_embeddings = getattr(
        getattr(arcpy, "geoai", None), "GenerateEmbeddingsUsingAIModels", None
    )
    if not generate_embeddings:
        raise arcpy.ExecuteError(
            "Generate Embeddings Using AI Models is unavailable in this ArcGIS Pro "
            "installation. Install or update the GeoAI deep-learning tools required "
            "by the ArcGIS Pro GeoAI toolbox."
        )
    return generate_embeddings(**kwargs)


def _merge_embedding_chunks(
    chunk_outputs,
    output_embeddings,
):
    arcpy.management.Merge(
        inputs=";".join(chunk_outputs),
        output=output_embeddings,
        field_mappings=None,
        add_source="NO_SOURCE_INFO",
        field_match_mode="AUTOMATIC",
    )
    if not _valid_embedding_output(output_embeddings):
        raise arcpy.ExecuteError(
            "The direct embedding merge did not create a valid feature class."
        )


def _embedding_checkpoint_workspace(
    cache_root,
    model,
    grid_size,
    batch_size,
    output_spatial_reference,
):
    model_size = os.path.getsize(model) if os.path.isfile(model) else None
    wkid = (
        getattr(output_spatial_reference, "factoryCode", 0)
        or getattr(output_spatial_reference, "latestWkid", 0)
        or output_spatial_reference.name
    )
    checkpoint_properties = {
        "model": os.path.abspath(model).lower(),
        "model_size": model_size,
        "grid_size": int(grid_size),
        "output_wkid": wkid,
        "chunk_pixels": EMBEDDING_CHUNK_PIXELS,
        "input_strategy": "per_chunk_raster_v1",
    }
    checkpoint_workspace = _hashed_embedding_workspace(
        cache_root, checkpoint_properties
    )
    if arcpy.Exists(checkpoint_workspace):
        return checkpoint_workspace

    legacy_batch_sizes = [int(batch_size)] + [
        value for value in range(1, 129) if value != int(batch_size)
    ]
    for legacy_batch_size in legacy_batch_sizes:
        legacy_properties = dict(checkpoint_properties)
        legacy_properties["batch_size"] = legacy_batch_size
        legacy_workspace = _hashed_embedding_workspace(
            cache_root, legacy_properties
        )
        if arcpy.Exists(legacy_workspace):
            return legacy_workspace
    return checkpoint_workspace


def _hashed_embedding_workspace(cache_root, checkpoint_properties):
    checkpoint_key = json.dumps(checkpoint_properties, sort_keys=True)
    checkpoint_id = hashlib.sha256(
        checkpoint_key.encode("utf-8")
    ).hexdigest()[:12]
    return os.path.join(cache_root, f"embeddings_{checkpoint_id}.gdb")


def _release_gpu_memory():
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:
        pass
    try:
        arcpy.management.ClearWorkspaceCache()
    except Exception:
        pass


def _valid_embedding_checkpoint(feature_class):
    if not os.path.isfile(_checkpoint_marker(feature_class)):
        return False
    return _has_embedding_field(feature_class)


def _has_embedding_field(feature_class):
    if not arcpy.Exists(feature_class):
        return False
    try:
        return any(
            field.type.upper() == "BLOB"
            for field in arcpy.ListFields(feature_class)
        )
    except Exception:
        return False


def _valid_embedding_output(feature_class):
    if not _has_embedding_field(feature_class):
        return False
    try:
        return int(arcpy.management.GetCount(feature_class)[0]) > 0
    except Exception:
        return False


def _embedding_chunk_extents(
    image_service_cache,
    analysis_extent,
    analysis_spatial_reference,
    grid_size,
):
    raster_spatial_reference = image_service_cache["spatial_reference"]
    cell_width = image_service_cache["cell_width"]
    cell_height = image_service_cache["cell_height"]
    projected_extent = _project_extent(
        analysis_extent,
        analysis_spatial_reference,
        raster_spatial_reference,
    )
    raster_extent = image_service_cache["source_extent"]
    xmin = max(projected_extent.XMin, raster_extent.XMin)
    ymin = max(projected_extent.YMin, raster_extent.YMin)
    xmax = min(projected_extent.XMax, raster_extent.XMax)
    ymax = min(projected_extent.YMax, raster_extent.YMax)
    if xmin >= xmax or ymin >= ymax:
        raise arcpy.ExecuteError(
            "The embedding analysis extent does not overlap the cached post-event imagery."
        )

    embedding_stride_pixels = max(16, 16 * int(grid_size))
    chunk_width_pixels = max(
        embedding_stride_pixels,
        (EMBEDDING_CHUNK_PIXELS // embedding_stride_pixels)
        * embedding_stride_pixels,
    )
    chunk_width = chunk_width_pixels * cell_width
    chunk_height = chunk_width_pixels * cell_height
    column_count = math.ceil((xmax - xmin) / chunk_width)
    row_count = math.ceil((ymax - ymin) / chunk_height)
    chunk_extents = []
    for row in range(row_count):
        chunk_ymax = ymax - row * chunk_height
        chunk_ymin = max(ymin, chunk_ymax - chunk_height)
        for column in range(column_count):
            chunk_xmin = xmin + column * chunk_width
            chunk_xmax = min(xmax, chunk_xmin + chunk_width)
            chunk_extents.append(
                _spatial_extent(
                    chunk_xmin,
                    chunk_ymin,
                    chunk_xmax,
                    chunk_ymax,
                    raster_spatial_reference,
                )
            )
    return chunk_extents


def _prepare_embedding_chunk_raster(
    chunk_raster,
    chunk_extent,
    image_service_cache,
):
    if _valid_raster_output(chunk_raster):
        return chunk_raster
    _delete_cached_raster(chunk_raster)

    tile_paths = [
        tile_path
        for tile_path, xmin, ymin, xmax, ymax in image_service_cache["tile_records"]
        if not (
            xmax <= chunk_extent.XMin
            or xmin >= chunk_extent.XMax
            or ymax <= chunk_extent.YMin
            or ymin >= chunk_extent.YMax
        )
    ]
    if not tile_paths:
        raise arcpy.ExecuteError(
            "No cached image-service tiles intersect an embedding chunk."
        )

    first_raster = arcpy.Raster(tile_paths[0])
    band_count = int(
        float(
            arcpy.management.GetRasterProperties(
                tile_paths[0], "BANDCOUNT"
            ).getOutput(0)
        )
    )
    with arcpy.EnvManager(
        extent=chunk_extent,
        outputCoordinateSystem=image_service_cache["spatial_reference"],
        cellSize=image_service_cache["cell_width"],
        snapRaster=tile_paths[0],
        compression="LZW",
    ):
        arcpy.management.MosaicToNewRaster(
            input_rasters=tile_paths,
            output_location=os.path.dirname(chunk_raster),
            raster_dataset_name_with_extension=os.path.basename(chunk_raster),
            coordinate_system_for_the_raster=image_service_cache[
                "spatial_reference"
            ],
            pixel_type=_mosaic_pixel_type(first_raster.pixelType),
            cellsize=image_service_cache["cell_width"],
            number_of_bands=band_count,
            mosaic_method="FIRST",
            mosaic_colormap_mode="FIRST",
        )
    if not _valid_raster_output(chunk_raster):
        _delete_cached_raster(chunk_raster)
        raise arcpy.ExecuteError(
            "Could not create a readable local raster for an embedding chunk."
        )
    return chunk_raster


def _mosaic_pixel_type(pixel_type):
    return {
        "U1": "1_BIT",
        "U2": "2_BIT",
        "U4": "4_BIT",
        "U8": "8_BIT_UNSIGNED",
        "S8": "8_BIT_SIGNED",
        "U16": "16_BIT_UNSIGNED",
        "S16": "16_BIT_SIGNED",
        "U32": "32_BIT_UNSIGNED",
        "S32": "32_BIT_SIGNED",
        "F32": "32_BIT_FLOAT",
        "F64": "64_BIT",
    }.get(str(pixel_type).upper(), "8_BIT_UNSIGNED")


def _delete_cached_raster(raster_path):
    if not raster_path:
        return
    try:
        arcpy.management.ClearWorkspaceCache()
    except Exception:
        pass
    try:
        if arcpy.Exists(raster_path):
            arcpy.management.Delete(raster_path)
    except Exception:
        pass
    raster_root = os.path.splitext(raster_path)[0]
    candidates = set(glob.glob(f"{raster_path}*"))
    candidates.update(glob.glob(f"{raster_root}.tfw"))
    for candidate in candidates:
        try:
            if os.path.isfile(candidate):
                os.remove(candidate)
        except OSError:
            pass


def _spatial_extent(xmin, ymin, xmax, ymax, spatial_reference):
    return arcpy.Polygon(
        arcpy.Array(
            [
                arcpy.Point(xmin, ymin),
                arcpy.Point(xmin, ymax),
                arcpy.Point(xmax, ymax),
                arcpy.Point(xmax, ymin),
            ]
        ),
        spatial_reference,
    ).extent


def _image_service_raster_properties(raster, service_url, messages):
    description = arcpy.Describe(raster)
    source_spatial_reference = getattr(description, "spatialReference", None)
    cell_width = abs(float(getattr(description, "meanCellWidth", 0) or 0))
    cell_height = abs(float(getattr(description, "meanCellHeight", 0) or 0))
    property_source = "layer description"

    if not cell_width or not cell_height:
        try:
            cell_width = abs(
                float(
                    arcpy.management.GetRasterProperties(
                        raster, "CELLSIZEX"
                    ).getOutput(0)
                )
            )
            cell_height = abs(
                float(
                    arcpy.management.GetRasterProperties(
                        raster, "CELLSIZEY"
                    ).getOutput(0)
                )
            )
            property_source = "ArcPy raster properties"
        except Exception:
            cell_width = 0
            cell_height = 0

    has_spatial_reference = (
        source_spatial_reference
        and getattr(source_spatial_reference, "name", "Unknown") != "Unknown"
    )
    service_info_error = None
    if not has_spatial_reference or not cell_width or not cell_height:
        try:
            service_info = _request_json(
                f"{service_url}?{urllib.parse.urlencode({'f': 'json'})}"
            )
            if service_info.get("error"):
                raise RuntimeError(service_info["error"].get("message", "REST error"))

            if not cell_width:
                cell_width = abs(float(service_info.get("pixelSizeX") or 0))
            if not cell_height:
                cell_height = abs(float(service_info.get("pixelSizeY") or 0))
            if not has_spatial_reference:
                spatial_reference_info = service_info.get("spatialReference") or {}
                wkid = (
                    spatial_reference_info.get("latestWkid")
                    or spatial_reference_info.get("wkid")
                )
                if wkid:
                    source_spatial_reference = arcpy.SpatialReference(int(wkid))
                elif spatial_reference_info.get("wkt"):
                    source_spatial_reference = arcpy.SpatialReference()
                    source_spatial_reference.loadFromString(
                        spatial_reference_info["wkt"]
                    )
            property_source = "image-service REST metadata"
        except Exception as error:
            service_info_error = error

    if (
        not source_spatial_reference
        or getattr(source_spatial_reference, "name", "Unknown") == "Unknown"
        or not cell_width
        or not cell_height
    ):
        detail = f" Details: {service_info_error}" if service_info_error else ""
        raise arcpy.ExecuteError(
            "The post-event image service did not expose a usable coordinate system "
            f"and native pixel size through ArcPy or its REST endpoint.{detail}"
        )

    messages.addMessage(
        f"Post-event image-service native pixel size: {cell_width:g} by "
        f"{cell_height:g} ({property_source})."
    )
    return source_spatial_reference, cell_width, cell_height


def _image_service_url(raster):
    candidates = []
    try:
        candidates.append(raster.dataSource)
    except Exception:
        pass
    try:
        candidates.append(arcpy.Describe(raster).catalogPath)
    except Exception:
        pass
    return next(
        (
            value.split("?")[0].rstrip("/")
            for value in candidates
            if isinstance(value, str) and "/imageserver" in value.lower()
        ),
        None,
    )


def _project_extent(extent, source_spatial_reference, target_spatial_reference):
    source_wkid = (
        getattr(source_spatial_reference, "factoryCode", 0)
        or getattr(source_spatial_reference, "latestWkid", 0)
        or 0
    )
    target_wkid = (
        getattr(target_spatial_reference, "factoryCode", 0)
        or getattr(target_spatial_reference, "latestWkid", 0)
        or 0
    )
    if source_wkid and source_wkid == target_wkid:
        return extent

    extent_polygon = arcpy.Polygon(
        arcpy.Array(
            [
                arcpy.Point(extent.XMin, extent.YMin),
                arcpy.Point(extent.XMin, extent.YMax),
                arcpy.Point(extent.XMax, extent.YMax),
                arcpy.Point(extent.XMax, extent.YMin),
            ]
        ),
        source_spatial_reference,
    )
    transformations = arcpy.ListTransformations(
        source_spatial_reference, target_spatial_reference
    )
    transformation = transformations[0] if transformations else None
    return extent_polygon.projectAs(
        target_spatial_reference, transformation
    ).extent


def _ensure_web_mercator_raster(raster, label, messages):
    spatial_reference = getattr(arcpy.Describe(raster), "spatialReference", None)
    if not spatial_reference or getattr(spatial_reference, "name", "Unknown") == "Unknown":
        raise arcpy.ExecuteError(
            f"{label} must have a defined coordinate system before it can be processed."
        )
    wkid = (
        getattr(spatial_reference, "factoryCode", 0)
        or getattr(spatial_reference, "latestWkid", 0)
        or 0
    )
    if wkid in WEB_MERCATOR_WKIDS or getattr(spatial_reference, "type", "") == "Projected":
        return raster

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
        for release_number, entry in catalog.items():
            title = entry.get("itemTitle")
            metadata_url = entry.get("metadataLayerUrl")
            tile_url = entry.get("itemURL")
            date_match = re.search(r"(\d{4}-\d{2}-\d{2})", title or "")
            if title and metadata_url and tile_url and date_match:
                releases.append(
                    (
                        title,
                        date_match.group(1),
                        metadata_url,
                        tile_url,
                        int(release_number),
                    )
                )
        _WAYBACK_RELEASES = sorted(releases, key=lambda item: item[1], reverse=True)
    except Exception:
        return []
    return _WAYBACK_RELEASES


def _get_wayback_release(release_title):
    release = next(
        (item for item in _get_wayback_releases() if item[0] == release_title), None
    )
    if release is None:
        raise arcpy.ExecuteError(
            "The selected Wayback release could not be resolved. Refresh the toolbox "
            "while connected to the internet or provide input imagery."
        )
    return release


def _get_wayback_filter_extent(aoi, target_features):
    dataset = aoi or target_features
    if dataset:
        try:
            description = arcpy.Describe(dataset)
            spatial_reference = description.spatialReference
            if spatial_reference and spatial_reference.name != "Unknown":
                return description.extent, spatial_reference
        except Exception:
            return None

    environment_extent = _get_environment_extent()
    if environment_extent:
        spatial_reference = getattr(environment_extent, "spatialReference", None)
        if spatial_reference and getattr(spatial_reference, "name", "Unknown") != "Unknown":
            return environment_extent, spatial_reference

    try:
        active_view = arcpy.mp.ArcGISProject("CURRENT").activeView
        display_extent = active_view.camera.getExtent()
        spatial_reference = getattr(display_extent, "spatialReference", None)
        if spatial_reference and getattr(spatial_reference, "name", "Unknown") != "Unknown":
            return display_extent, spatial_reference
    except Exception:
        pass
    return None


def _wayback_filter_key(filter_extent):
    if not filter_extent:
        return None
    extent, spatial_reference = filter_extent
    wkid = (
        getattr(spatial_reference, "factoryCode", 0)
        or getattr(spatial_reference, "latestWkid", 0)
        or spatial_reference.name
    )
    return (
        round(extent.XMin, 3),
        round(extent.YMin, 3),
        round(extent.XMax, 3),
        round(extent.YMax, 3),
        wkid,
    )


def _get_wayback_releases_with_local_changes(
    analysis_extent, spatial_reference, level=18
):
    releases = _get_wayback_releases()
    if not releases:
        return []

    xmin, ymin, xmax, ymax = _web_mercator_envelope(
        analysis_extent, spatial_reference
    )
    resolution = WEB_MERCATOR_INITIAL_RESOLUTION / (2**level)
    tile_span = resolution * 256
    column = math.floor((((xmin + xmax) / 2) + WEB_MERCATOR_ORIGIN) / tile_span)
    row = math.floor((WEB_MERCATOR_ORIGIN - ((ymin + ymax) / 2)) / tile_span)
    releases_by_number = {release[4]: release for release in releases}
    release_indexes = {
        release[4]: index for index, release in enumerate(releases)
    }
    current_release_number = releases[0][4]
    local_release_numbers = []

    while current_release_number is not None:
        response = _request_json(
            f"{WAYBACK_MAP_SERVER_URL}/tilemap/{current_release_number}/"
            f"{level}/{row}/{column}"
        )
        if not response.get("data") or not response["data"][0]:
            break

        selected = response.get("select") or []
        changed_release_number = (
            int(selected[0]) if selected and selected[0] else current_release_number
        )
        if changed_release_number not in local_release_numbers:
            local_release_numbers.append(changed_release_number)

        release_index = release_indexes.get(changed_release_number)
        if release_index is None or release_index + 1 >= len(releases):
            break
        current_release_number = releases[release_index + 1][4]

    return [
        releases_by_number[release_number]
        for release_number in local_release_numbers
        if release_number in releases_by_number
    ]


def _validate_wayback_coverage(
    release_title, analysis_extent, spatial_reference, label, messages
):
    release = _get_wayback_release(release_title)

    envelope = _web_mercator_envelope(analysis_extent, spatial_reference)
    query = urllib.parse.urlencode(
        {
            "f": "json",
            "geometry": ",".join(f"{value:.6f}" for value in envelope),
            "geometryType": "esriGeometryEnvelope",
            "inSR": "3857",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "SRC_DATE2,SRC_RES,SRC_DESC,NICE_NAME,DrawOrder",
            "returnGeometry": "false",
        }
    )
    try:
        response = _request_json(f"{release[2]}/5/query?{query}")
    except Exception as error:
        messages.addWarningMessage(
            f"Could not validate {label.lower()} Wayback metadata over the analysis "
            f"area. The selected release will still be used. Details: {error}"
        )
        return None

    if response.get("error"):
        messages.addWarningMessage(
            f"Could not validate {label.lower()} Wayback metadata over the analysis "
            "area. The selected release will still be used."
        )
        return None

    metadata = {
        (
            attributes.get("SRC_DATE2"),
            attributes.get("SRC_RES"),
            attributes.get("SRC_DESC") or "Unknown source",
            attributes.get("NICE_NAME") or "Unnamed imagery",
            attributes.get("DrawOrder") or 0,
        )
        for feature in response.get("features", [])
        for attributes in [feature.get("attributes", {})]
    }
    if not metadata:
        raise arcpy.ExecuteError(
            f"The selected {label.lower()} Wayback release has no imagery metadata "
            "covering the analysis area. Choose another release or input imagery."
        )

    top_draw_order = max(item[4] for item in metadata)
    displayed_metadata = frozenset(
        item[:4] for item in metadata if item[4] == top_draw_order
    )
    dated_metadata = [item for item in displayed_metadata if item[0] is not None]
    newest = min(
        dated_metadata or displayed_metadata,
        key=lambda item: (
            float(item[1]) if item[1] is not None else float("inf"),
            -(item[0] or 0),
        ),
    )
    acquisition_date = (
        datetime.fromtimestamp(newest[0] / 1000, timezone.utc).strftime("%Y-%m-%d")
        if newest[0] is not None
        else "unknown"
    )
    resolution = (
        f"{float(newest[1]):g} m" if newest[1] is not None else "unknown resolution"
    )
    messages.addMessage(
        f"{label} Wayback coverage: local imagery acquired {acquisition_date}; "
        f"{newest[2]}; {newest[3]}; {resolution}."
    )
    return displayed_metadata


def _web_mercator_envelope(extent, spatial_reference):
    wkid = (
        getattr(spatial_reference, "factoryCode", 0)
        or getattr(spatial_reference, "latestWkid", 0)
        or 0
    )
    if wkid in WEB_MERCATOR_WKIDS:
        projected_extent = extent
    else:
        extent_polygon = arcpy.Polygon(
            arcpy.Array(
                [
                    arcpy.Point(extent.XMin, extent.YMin),
                    arcpy.Point(extent.XMin, extent.YMax),
                    arcpy.Point(extent.XMax, extent.YMax),
                    arcpy.Point(extent.XMax, extent.YMin),
                ]
            ),
            spatial_reference,
        )
        projected_extent = extent_polygon.projectAs(
            arcpy.SpatialReference(3857)
        ).extent
    return (
        projected_extent.XMin,
        projected_extent.YMin,
        projected_extent.XMax,
        projected_extent.YMax,
    )


def _wayback_cell_size(metadata, default_cell_size):
    resolutions = [
        float(item[1])
        for item in metadata or []
        if item[1] is not None and float(item[1]) > 0
    ]
    return max(min(resolutions), default_cell_size) if resolutions else default_cell_size


def _resolve_post_event_imagery(
    source,
    input_raster,
    wayback_release_title,
    analysis_extent,
    spatial_reference,
    messages,
):
    if source == "Input Imagery":
        return input_raster, None, None

    if source == "Current World Imagery":
        raster, cache = _materialize_tiled_embedding_cache(
            "Current World Imagery",
            WORLD_IMAGERY_TILE_URL,
            "current_world_imagery",
            analysis_extent,
            spatial_reference,
            0.3,
            messages,
        )
        return raster, cache, None

    metadata = _validate_wayback_coverage(
        wayback_release_title,
        analysis_extent,
        spatial_reference,
        "Post-event",
        messages,
    )
    raster, cache = _materialize_wayback_embedding_cache(
        wayback_release_title,
        analysis_extent,
        spatial_reference,
        _wayback_cell_size(metadata, 0.3),
        messages,
    )
    return raster, cache, metadata


def _materialize_wayback_embedding_cache(
    release_title,
    analysis_extent,
    spatial_reference,
    requested_cell_size,
    messages,
):
    release = _get_wayback_release(release_title)

    return _materialize_tiled_embedding_cache(
        release_title,
        release[3],
        release[4],
        analysis_extent,
        spatial_reference,
        requested_cell_size,
        messages,
    )


def _materialize_tiled_embedding_cache(
    source_title,
    tile_url_template,
    source_id,
    analysis_extent,
    spatial_reference,
    requested_cell_size,
    messages,
):
    grid = _tiled_imagery_grid(
        analysis_extent,
        spatial_reference,
        requested_cell_size,
    )
    cache_root = _tiled_embedding_cache_root(
        source_id, tile_url_template, grid
    )
    block_folder = os.path.join(cache_root, "blocks")
    staging_root = os.path.join(cache_root, "staging")
    os.makedirs(block_folder, exist_ok=True)
    os.makedirs(staging_root, exist_ok=True)
    web_mercator = arcpy.SpatialReference(3857)
    projection_text = web_mercator.exportToString()
    block_records = []
    reused_block_count = 0
    block_row_starts = range(
        grid["row_min"], grid["row_max"] + 1, WAYBACK_BLOCK_TILES
    )
    block_column_starts = range(
        grid["column_min"], grid["column_max"] + 1, WAYBACK_BLOCK_TILES
    )
    block_count = len(block_row_starts) * len(block_column_starts)

    messages.addMessage(f"Resumable {source_title} processing cache: {cache_root}")
    messages.addMessage(
        f"Caching {grid['tile_count']:,} {source_title} tiles as "
        f"{block_count:,} aligned raster blocks at level {grid['level']} "
        f"({grid['resolution']:.3f} m pixels)..."
    )
    try:
        for block_row in block_row_starts:
            last_row = min(
                grid["row_max"], block_row + WAYBACK_BLOCK_TILES - 1
            )
            for block_column in block_column_starts:
                last_column = min(
                    grid["column_max"],
                    block_column + WAYBACK_BLOCK_TILES - 1,
                )
                block_extent = _wayback_tile_range_extent(
                    block_row,
                    last_row,
                    block_column,
                    last_column,
                    grid["tile_span"],
                    web_mercator,
                )
                block_path = os.path.join(
                    block_folder,
                    f"wayback_{block_row}_{block_column}.tif",
                )
                expected_columns = (last_column - block_column + 1) * 256
                expected_rows = (last_row - block_row + 1) * 256
                block_records.append(
                    (
                        block_path,
                        block_extent.XMin,
                        block_extent.YMin,
                        block_extent.XMax,
                        block_extent.YMax,
                    )
                )
                if _valid_tiled_imagery_block(
                    block_path,
                    expected_columns,
                    expected_rows,
                    grid["resolution"],
                    block_extent,
                ):
                    reused_block_count += 1
                    continue

                _delete_cached_raster(block_path)
                _delete_checkpoint_marker(block_path)
                staging_folder = os.path.join(
                    staging_root, f"block_{block_row}_{block_column}"
                )
                shutil.rmtree(staging_folder, ignore_errors=True)
                os.makedirs(staging_folder, exist_ok=True)
                tile_paths = []
                for row in range(block_row, last_row + 1):
                    for column in range(block_column, last_column + 1):
                        tile_path = os.path.join(
                            staging_folder, f"tile_{row}_{column}.jpg"
                        )
                        _download_tiled_imagery_tile(
                            tile_url_template,
                            grid["level"],
                            row,
                            column,
                            tile_path,
                            grid["resolution"],
                            grid["tile_span"],
                            projection_text,
                        )
                        tile_paths.append(tile_path)

                with arcpy.EnvManager(
                    extent=block_extent,
                    snapRaster=tile_paths[0],
                    cellSize=grid["resolution"],
                    outputCoordinateSystem=web_mercator,
                    compression="LZW",
                ):
                    arcpy.management.MosaicToNewRaster(
                        input_rasters=tile_paths,
                        output_location=block_folder,
                        raster_dataset_name_with_extension=os.path.basename(
                            block_path
                        ),
                        coordinate_system_for_the_raster=web_mercator,
                        pixel_type="8_BIT_UNSIGNED",
                        cellsize=grid["resolution"],
                        number_of_bands=3,
                        mosaic_method="FIRST",
                        mosaic_colormap_mode="FIRST",
                    )
                if not _valid_tiled_imagery_block(
                    block_path,
                    expected_columns,
                    expected_rows,
                    grid["resolution"],
                    block_extent,
                    require_marker=False,
                ):
                    _delete_cached_raster(block_path)
                    raise arcpy.ExecuteError(
                        f"{source_title} block assembly did not create the expected "
                        "readable "
                        f"raster: {block_path}"
                    )
                _write_checkpoint_marker(block_path)
                try:
                    arcpy.management.ClearWorkspaceCache()
                except Exception:
                    pass
                shutil.rmtree(staging_folder, ignore_errors=True)

        if reused_block_count:
            messages.addMessage(
                f"Resumed Wayback cache with {reused_block_count:,} of "
                f"{block_count:,} raster blocks already complete."
            )
        shutil.rmtree(staging_root, ignore_errors=True)
        source_extent = _wayback_tile_range_extent(
            grid["row_min"],
            grid["row_max"],
            grid["column_min"],
            grid["column_max"],
            grid["tile_span"],
            web_mercator,
        )
        messages.addMessage(
            f"Cached {source_title} blocks are ready for extent-based processing."
        )
        return block_records[0][0], {
            "cache_root": cache_root,
            "tile_records": tuple(block_records),
            "source_extent": source_extent,
            "spatial_reference": web_mercator,
            "cell_width": grid["resolution"],
            "cell_height": grid["resolution"],
        }
    except Exception as error:
        raise arcpy.ExecuteError(
            f"Could not complete the resumable {source_title} cache. Run the "
            f"tool again to continue from {cache_root}. Details: {error}"
        )


def _tiled_imagery_grid(
    analysis_extent,
    spatial_reference,
    requested_cell_size,
):
    xmin, ymin, xmax, ymax = _web_mercator_envelope(
        analysis_extent, spatial_reference
    )
    level = max(
        0,
        min(
            23,
            math.floor(
                math.log(
                    WEB_MERCATOR_INITIAL_RESOLUTION / requested_cell_size, 2
                )
            ),
        ),
    )
    resolution = WEB_MERCATOR_INITIAL_RESOLUTION / (2**level)
    tile_span = resolution * 256
    column_min = math.floor((xmin + WEB_MERCATOR_ORIGIN) / tile_span)
    column_max = math.floor(
        (xmax + WEB_MERCATOR_ORIGIN - resolution / 1000) / tile_span
    )
    row_min = math.floor((WEB_MERCATOR_ORIGIN - ymax) / tile_span)
    row_max = math.floor(
        (WEB_MERCATOR_ORIGIN - ymin - resolution / 1000) / tile_span
    )
    tile_count = (column_max - column_min + 1) * (row_max - row_min + 1)
    matrix_size = 2**level
    if (
        tile_count < 1
        or column_min < 0
        or row_min < 0
        or column_max >= matrix_size
        or row_max >= matrix_size
    ):
        raise arcpy.ExecuteError(
            "The AOI/Extent falls outside the supported World Imagery Wayback "
            "Web Mercator tile grid."
        )
    return {
        "level": level,
        "resolution": resolution,
        "tile_span": tile_span,
        "column_min": column_min,
        "column_max": column_max,
        "row_min": row_min,
        "row_max": row_max,
        "tile_count": tile_count,
    }


def _tiled_embedding_cache_root(source_id, tile_url_template, grid):
    cache_key = json.dumps(
        {
            "cache_format": WAYBACK_CACHE_FORMAT_VERSION,
            "source_id": source_id,
            "tile_url": tile_url_template,
            "level": grid["level"],
            "rows": [grid["row_min"], grid["row_max"]],
            "columns": [grid["column_min"], grid["column_max"]],
            "block_tiles": WAYBACK_BLOCK_TILES,
        },
        sort_keys=True,
    )
    cache_id = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:16]
    return os.path.join(
        arcpy.env.scratchFolder, f"DamageAssessment_Wayback_{cache_id}"
    )


def _valid_tiled_imagery_block(
    raster_path,
    expected_columns,
    expected_rows,
    resolution,
    expected_extent,
    require_marker=True,
):
    if require_marker and not os.path.isfile(_checkpoint_marker(raster_path)):
        return False
    if not _valid_raster_output(raster_path):
        return False
    try:
        properties = {
            name: arcpy.management.GetRasterProperties(
                raster_path, name
            ).getOutput(0)
            for name in (
                "COLUMNCOUNT",
                "ROWCOUNT",
                "BANDCOUNT",
                "CELLSIZEX",
                "CELLSIZEY",
            )
        }
        raster = arcpy.Raster(raster_path)
        description = arcpy.Describe(raster_path)
        spatial_reference = description.spatialReference
        actual_extent = description.extent
        wkid = (
            getattr(spatial_reference, "factoryCode", 0)
            or getattr(spatial_reference, "latestWkid", 0)
            or 0
        )
        tolerance = resolution / 1000.0
        extent_matches = all(
            abs(actual - expected) <= tolerance
            for actual, expected in (
                (actual_extent.XMin, expected_extent.XMin),
                (actual_extent.YMin, expected_extent.YMin),
                (actual_extent.XMax, expected_extent.XMax),
                (actual_extent.YMax, expected_extent.YMax),
            )
        )
        return (
            int(float(properties["COLUMNCOUNT"])) == expected_columns
            and int(float(properties["ROWCOUNT"])) == expected_rows
            and int(float(properties["BANDCOUNT"])) == 3
            and str(raster.pixelType).upper() == "U8"
            and abs(float(properties["CELLSIZEX"]) - resolution) <= tolerance
            and abs(abs(float(properties["CELLSIZEY"])) - resolution) <= tolerance
            and wkid in WEB_MERCATOR_WKIDS
            and extent_matches
        )
    except Exception:
        return False


def _wayback_tile_range_extent(
    first_row,
    last_row,
    first_column,
    last_column,
    tile_span,
    spatial_reference,
):
    return _spatial_extent(
        -WEB_MERCATOR_ORIGIN + first_column * tile_span,
        WEB_MERCATOR_ORIGIN - (last_row + 1) * tile_span,
        -WEB_MERCATOR_ORIGIN + (last_column + 1) * tile_span,
        WEB_MERCATOR_ORIGIN - first_row * tile_span,
        spatial_reference,
    )


def _download_tiled_imagery_tile(
    tile_url_template,
    level,
    row,
    column,
    tile_path,
    resolution,
    tile_span,
    projection_text,
):
    tile_url = (
        tile_url_template
        .replace("{level}", str(level))
        .replace("{row}", str(row))
        .replace("{col}", str(column))
    )
    request = urllib.request.Request(
        tile_url, headers={"User-Agent": "ArcGIS-Damage-Assessment"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        image_bytes = response.read()
    if not image_bytes.startswith(b"\xff\xd8"):
        raise RuntimeError(
            f"Wayback returned a non-JPEG response for tile {level}/{row}/{column}."
        )
    with open(tile_path, "wb") as tile_file:
        tile_file.write(image_bytes)

    tile_xmin = -WEB_MERCATOR_ORIGIN + column * tile_span
    tile_ymax = WEB_MERCATOR_ORIGIN - row * tile_span
    with open(
        os.path.splitext(tile_path)[0] + ".jgw", "w", encoding="ascii"
    ) as file_handle:
        file_handle.write(
            f"{resolution}\n0\n0\n{-resolution}\n"
            f"{tile_xmin + resolution / 2}\n"
            f"{tile_ymax - resolution / 2}\n"
        )
    with open(
        os.path.splitext(tile_path)[0] + ".prj", "w", encoding="utf-8"
    ) as file_handle:
        file_handle.write(projection_text)


def _materialize_wayback_imagery(
    release_title,
    analysis_extent,
    spatial_reference,
    requested_cell_size,
    output_label,
    messages,
):
    release = _get_wayback_release(release_title)

    grid = _tiled_imagery_grid(
        analysis_extent,
        spatial_reference,
        requested_cell_size,
    )
    if grid["tile_count"] > MAX_WAYBACK_TILES:
        raise arcpy.ExecuteError(
            f"The analysis area requires {grid['tile_count']:,} Wayback tiles at "
            f"level {grid['level']} ({grid['resolution']:.3f} m pixels), exceeding "
            f"the {MAX_WAYBACK_TILES:,}-tile safety limit. Reduce the AOI/Extent "
            "or use a local raster."
        )

    scratch_folder = arcpy.env.scratchFolder
    output_raster = arcpy.CreateUniqueName(
        f"Wayback_{output_label}.tif", scratch_folder
    )
    tile_folder = f"{os.path.splitext(output_raster)[0]}_tiles"
    os.makedirs(tile_folder, exist_ok=True)
    web_mercator = arcpy.SpatialReference(3857)
    projection_text = web_mercator.exportToString()
    tile_paths = []
    messages.addMessage(
        f"Materializing {release_title}: downloading {grid['tile_count']:,} tiles "
        f"at level {grid['level']} ({grid['resolution']:.3f} m pixels)..."
    )
    try:
        for row in range(grid["row_min"], grid["row_max"] + 1):
            for column in range(grid["column_min"], grid["column_max"] + 1):
                tile_path = os.path.join(tile_folder, f"tile_{row}_{column}.jpg")
                _download_tiled_imagery_tile(
                    release[3],
                    grid["level"],
                    row,
                    column,
                    tile_path,
                    grid["resolution"],
                    grid["tile_span"],
                    projection_text,
                )
                tile_paths.append(tile_path)

        arcpy.management.MosaicToNewRaster(
            input_rasters=tile_paths,
            output_location=os.path.dirname(output_raster),
            raster_dataset_name_with_extension=os.path.basename(output_raster),
            coordinate_system_for_the_raster=web_mercator,
            pixel_type="8_BIT_UNSIGNED",
            cellsize=grid["resolution"],
            number_of_bands=3,
            mosaic_method="FIRST",
            mosaic_colormap_mode="FIRST",
        )
        shutil.rmtree(tile_folder, ignore_errors=True)
        messages.addMessage(f"Created local Wayback raster: {output_raster}")
        return output_raster
    except Exception as error:
        if arcpy.Exists(output_raster):
            arcpy.management.Delete(output_raster)
        shutil.rmtree(tile_folder, ignore_errors=True)
        raise arcpy.ExecuteError(
            f"Could not materialize {release_title} as a local raster. "
            f"Use a smaller AOI/Extent or provide input imagery. Details: {error}"
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
            f"Using ArcGIS Online model {item_id} from cache: {model_path}"
        )
        return model_path

    partial_path = model_path + ".part"
    download_url = PORTAL_ITEM_URL.format(item_id=item_id) + "/data"
    messages.addMessage(
        f"Downloading ArcGIS Online model {item_id} ({file_name}). "
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


def _clip_targets_to_aoi(
    target_features,
    aoi,
    feature_type,
    output_workspace,
    messages,
):
    safe_feature_type = re.sub("[^A-Za-z0-9_]+", "_", feature_type)
    clipped_targets = arcpy.CreateUniqueName(
        f"Damage_{safe_feature_type}_AOI", output_workspace
    )
    messages.addMessage(
        "Clipping supplied target features to the Area of Interest..."
    )
    arcpy.analysis.PairwiseClip(target_features, aoi, clipped_targets)
    clipped_count = int(arcpy.management.GetCount(clipped_targets)[0])
    if clipped_count == 0:
        arcpy.management.Delete(clipped_targets)
        raise arcpy.ExecuteError(
            "No supplied target features intersect the Area of Interest."
        )
    messages.addMessage(
        f"Using {clipped_count:,} target feature(s) within the Area of Interest."
    )
    return clipped_targets


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
    output_features,
    scratch_workspace,
    messages,
):
    raw_features = arcpy.CreateUniqueName("sam3_raw", scratch_workspace)
    nms_features = arcpy.CreateUniqueName("sam3_nms", scratch_workspace)
    qa_features = arcpy.CreateUniqueName("sam3_qa_candidates", scratch_workspace)
    safe_feature_type = re.sub("[^A-Za-z0-9_]+", "_", feature_type)
    target_features = arcpy.CreateUniqueName(
        f"{_output_name_prefix(output_features)}_{safe_feature_type}", output_workspace
    )
    cell_size_units = _meters_to_spatial_units(cell_size, spatial_reference)

    try:
        messages.addMessage(f"Detecting {feature_type.lower()} with SAM3...")
        extraction_raster = _prepare_extraction_raster(source_imagery, messages)
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
            f"Removing only near-identical masks at {DUPLICATE_IOU_THRESHOLD:.0%} IoU; "
            "all other overlapping candidates are retained."
        )
        _remove_near_duplicate_polygons(
            raw_features, nms_features, DUPLICATE_IOU_THRESHOLD, scratch_workspace
        )
        detection_count = int(arcpy.management.GetCount(nms_features)[0])
        messages.addMessage(f"SAM3 detections after near-duplicate removal: {detection_count}")
        rejected_envelope_count = _remove_overgrown_polygon_masks(
            nms_features, qa_features, scratch_workspace
        )
        if rejected_envelope_count:
            messages.addMessage(
                f"Rejected {rejected_envelope_count:,} broad polygon mask(s) that enclosed "
                "multiple distinct smaller detections."
            )

        if FEATURE_PROFILES[feature_type]["regularize"]:
            _regularize_building_footprints(
                qa_features,
                target_features,
                spatial_reference,
                scratch_workspace,
                messages,
            )
        elif feature_type == "Roads":
            _clean_road_surfaces(
                qa_features, target_features, FEATURE_PROFILES[feature_type],
                spatial_reference, scratch_workspace, messages,
            )
        elif feature_type == "Agricultural Fields":
            _clean_agricultural_fields(
                qa_features, target_features, FEATURE_PROFILES[feature_type],
                spatial_reference, scratch_workspace, messages,
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


def _remove_near_duplicate_polygons(
    input_features, output_features, iou_threshold, scratch_workspace,
):
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
        arcpy.management.MakeFeatureLayer(
            input_features, selected_features, f"{field_delimiter} = 1"
        )
        arcpy.management.CopyFeatures(selected_features, output_features)
        arcpy.management.DeleteField(output_features, keep_field)
    finally:
        if arcpy.Exists(selected_features):
            arcpy.management.Delete(selected_features)


def _remove_overgrown_polygon_masks(input_features, output_features, scratch_workspace):
    """Reject broad masks that substantially enclose multiple distinct smaller masks."""
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
            if other_id == object_id or other_area >= area * 0.5:
                continue
            if geometry.disjoint(other_geometry):
                continue
            intersection = geometry.intersect(other_geometry, 4)
            intersection_area = intersection.getArea("GEODESIC", "SQUAREMETERS")
            if intersection_area / other_area >= 0.80:
                contained_masks.append((other_geometry, intersection_area))
        if len(contained_masks) < BUILDING_ENVELOPE_MIN_CHILDREN:
            continue
        covered_geometry = None
        for contained_geometry, _ in contained_masks:
            overlap_geometry = geometry.intersect(contained_geometry, 4)
            covered_geometry = (
                overlap_geometry
                if covered_geometry is None
                else covered_geometry.union(overlap_geometry)
            )
        covered_area = (
            covered_geometry.getArea("GEODESIC", "SQUAREMETERS")
            if covered_geometry else 0.0
        )
        coverage = covered_area / area
        distinct_masks = any(
            first_geometry.disjoint(second_geometry)
            for index, (first_geometry, _) in enumerate(contained_masks)
            for second_geometry, _ in contained_masks[index + 1:]
        )
        if distinct_masks and BUILDING_ENVELOPE_MIN_COVERAGE <= coverage <= BUILDING_ENVELOPE_MAX_COVERAGE:
            rejected_ids.add(object_id)

    keep_field = "AFE_KEEP_POLYGON"
    selected_features = arcpy.CreateUniqueName("polygon_mask_selection", scratch_workspace)
    try:
        arcpy.management.AddField(input_features, keep_field, "SHORT")
        with arcpy.da.UpdateCursor(input_features, ["OID@", keep_field]) as cursor:
            for object_id, _ in cursor:
                cursor.updateRow([object_id, int(object_id not in rejected_ids)])
        field_delimiter = arcpy.AddFieldDelimiters(input_features, keep_field)
        arcpy.management.MakeFeatureLayer(
            input_features, selected_features, f"{field_delimiter} = 1"
        )
        arcpy.management.CopyFeatures(selected_features, output_features)
        arcpy.management.DeleteField(output_features, keep_field)
    finally:
        if arcpy.Exists(selected_features):
            arcpy.management.Delete(selected_features)
    return len(rejected_ids)


def _prepare_extraction_raster(source_imagery, messages):
    spatial_reference = arcpy.Describe(source_imagery).spatialReference
    if getattr(spatial_reference, "type", "") == "Projected":
        messages.addMessage(
            "Using the selected projected imagery layer directly for feature extraction."
        )
        return source_imagery
    return _ensure_web_mercator_raster(
        source_imagery, "Feature extraction imagery", messages
    )


def _clean_road_surfaces(
    input_features, output_features, profile, spatial_reference, scratch_workspace, messages,
):
    repaired_features = arcpy.CreateUniqueName("road_repaired", scratch_workspace)
    road_inputs = arcpy.CreateUniqueName("road_qa_inputs", scratch_workspace)
    hole_filled_features = arcpy.CreateUniqueName("road_hole_filled", scratch_workspace)
    smoothed_features = arcpy.CreateUniqueName("road_smoothed", scratch_workspace)
    smoothing_tolerance = _meters_to_spatial_units(
        profile["road_smoothing_m"], spatial_reference
    )
    hole_fill_area = _square_meters_to_spatial_units(
        profile["road_hole_fill_sqm"], spatial_reference
    )
    try:
        messages.addMessage(
            "Running road-surface QA: repairing masks, bridging small occlusion gaps, "
            "filling small enclosed holes, and smoothing pixel stair-steps..."
        )
        arcpy.management.CopyFeatures(input_features, repaired_features)
        arcpy.management.RepairGeometry(repaired_features, "DELETE_NULL", "ESRI")
        if not int(arcpy.management.GetCount(repaired_features)[0]):
            raise arcpy.ExecuteError("Road QA repair produced no valid polygon masks.")
        rejected_mask_count = _remove_implausible_road_masks(
            repaired_features, road_inputs, profile, scratch_workspace
        )
        if rejected_mask_count:
            messages.addMessage(
                f"Rejected {rejected_mask_count:,} small or implausibly compact road mask(s)."
            )
        arcpy.management.EliminatePolygonPart(
            in_features=road_inputs,
            out_feature_class=hole_filled_features,
            condition="AREA",
            part_area=hole_fill_area,
            part_area_percent="0",
            part_option="CONTAINED_ONLY",
        )
        arcpy.cartography.SmoothPolygon(
            in_features=hole_filled_features,
            out_feature_class=smoothed_features,
            algorithm="PAEK",
            tolerance=smoothing_tolerance,
            endpoint_option="FIXED_ENDPOINT",
            error_option="RESOLVE_ERRORS",
        )
        arcpy.management.RepairGeometry(smoothed_features, "DELETE_NULL", "ESRI")
        if not int(arcpy.management.GetCount(smoothed_features)[0]):
            raise arcpy.ExecuteError("Road QA smoothing produced no valid polygons.")
        arcpy.management.CopyFeatures(smoothed_features, output_features)
        messages.addMessage(
            "Road-surface QA retained separate SAM3 masks, removed small and implausibly "
            "compact masks, filled 25 sq m enclosed holes, and applied 0.75 m smoothing."
        )
    except Exception as error:
        messages.addWarningMessage(
            f"Road-surface QA could not complete ({error}); retaining original road detections."
        )
        arcpy.management.CopyFeatures(input_features, output_features)
    finally:
        for dataset in (
            repaired_features, road_inputs, hole_filled_features, smoothed_features,
        ):
            if arcpy.Exists(dataset):
                arcpy.management.Delete(dataset)


def _remove_implausible_road_masks(input_features, output_features, profile, scratch_workspace):
    keep_field = "AFE_ROAD_QA_KEEP"
    selection_layer = arcpy.CreateUniqueName("road_mask_selection", scratch_workspace)
    minimum_area = profile["minimum_area_sqm"]
    rejected_count = 0
    try:
        arcpy.management.AddField(input_features, keep_field, "SHORT")
        with arcpy.da.UpdateCursor(input_features, ["SHAPE@", keep_field]) as cursor:
            for geometry, _ in cursor:
                area = geometry.getArea("GEODESIC", "SQUAREMETERS") if geometry else 0.0
                perimeter = geometry.getLength("GEODESIC", "METERS") if geometry else 0.0
                compactness = 4.0 * math.pi * area / perimeter ** 2 if perimeter else 0.0
                keep_mask = area >= minimum_area and not (area >= 1000.0 and compactness >= 0.70)
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


def _clean_agricultural_fields(
    input_features, output_features, profile, spatial_reference, scratch_workspace, messages,
):
    repaired_features = arcpy.CreateUniqueName("field_repaired", scratch_workspace)
    cleaned_features = arcpy.CreateUniqueName("field_hole_filled", scratch_workspace)
    smoothed_features = arcpy.CreateUniqueName("field_smoothed", scratch_workspace)
    hole_fill_area = _square_meters_to_spatial_units(
        profile["field_hole_fill_sqm"], spatial_reference
    )
    fragment_area = _square_meters_to_spatial_units(
        profile["field_fragment_max_sqm"], spatial_reference
    )
    smoothing_tolerance = _meters_to_spatial_units(
        profile["field_smoothing_m"], spatial_reference
    )
    try:
        messages.addMessage(
            "Running agricultural-field QA: repairing masks, removing small fragments, "
            "filling enclosed gaps, and smoothing one-pixel stair-steps..."
        )
        arcpy.management.CopyFeatures(input_features, repaired_features)
        arcpy.management.RepairGeometry(repaired_features, "DELETE_NULL", "ESRI")
        arcpy.management.EliminatePolygonPart(
            in_features=repaired_features,
            out_feature_class=cleaned_features,
            condition="AREA",
            part_area=hole_fill_area,
            part_area_percent="0",
            part_option="CONTAINED_ONLY",
        )
        arcpy.management.EliminatePolygonPart(
            in_features=cleaned_features,
            out_feature_class=smoothed_features,
            condition="AREA",
            part_area=fragment_area,
            part_area_percent="0",
            part_option="ANY",
        )
        arcpy.cartography.SmoothPolygon(
            in_features=smoothed_features,
            out_feature_class=output_features,
            algorithm="PAEK",
            tolerance=smoothing_tolerance,
            endpoint_option="FIXED_ENDPOINT",
            error_option="RESOLVE_ERRORS",
        )
        arcpy.management.RepairGeometry(output_features, "DELETE_NULL", "ESRI")
        if not int(arcpy.management.GetCount(output_features)[0]):
            raise arcpy.ExecuteError("Agricultural-field QA produced no valid polygons.")
        messages.addMessage(
            "Agricultural-field QA completed with 100 sq m hole/fragment cleanup and "
            "0.5 m boundary smoothing; separate fields remain separate."
        )
    except Exception as error:
        messages.addWarningMessage(
            f"Agricultural-field QA could not complete ({error}); retaining original field detections."
        )
        arcpy.management.CopyFeatures(input_features, output_features)
    finally:
        for dataset in (repaired_features, cleaned_features, smoothed_features):
            if arcpy.Exists(dataset):
                arcpy.management.Delete(dataset)


def _create_directional_road_connectors(
    road_features, output_connectors, profile, spatial_reference, scratch_workspace,
):
    """Build narrow candidate corridors only between strongly aligned road-mask ends."""
    bounding_rectangles = arcpy.CreateUniqueName("road_direction_rectangles", scratch_workspace)
    maximum_gap = _meters_to_spatial_units(profile["road_direction_gap_m"], spatial_reference)
    minimum_axis_alignment = math.cos(math.radians(profile["road_direction_alignment_deg"]))
    segment_endpoints = []
    try:
        arcpy.management.MinimumBoundingGeometry(
            in_features=road_features,
            out_feature_class=bounding_rectangles,
            geometry_type="RECTANGLE_BY_AREA",
            group_option="NONE",
            mbg_fields_option="NO_MBG_FIELDS",
        )
        with arcpy.da.SearchCursor(bounding_rectangles, ["SHAPE@"]) as cursor:
            for source_id, (rectangle,) in enumerate(cursor):
                endpoints = _rectangle_road_endpoints(rectangle)
                if endpoints:
                    first_endpoint, second_endpoint, width = endpoints
                    segment_endpoints.append((source_id, first_endpoint, second_endpoint, width))

        candidates = []
        for first_index, (first_id, first_start, first_end, first_width) in enumerate(segment_endpoints):
            first_axis = _unit_vector(first_start, first_end)
            if first_axis is None:
                continue
            for second_id, second_start, second_end, second_width in segment_endpoints[first_index + 1:]:
                if first_id == second_id:
                    continue
                second_axis = _unit_vector(second_start, second_end)
                if second_axis is None or abs(_dot_product(first_axis, second_axis)) < minimum_axis_alignment:
                    continue
                for first_end_index, first_point in enumerate((first_start, first_end)):
                    for second_end_index, second_point in enumerate((second_start, second_end)):
                        gap_vector = _unit_vector(first_point, second_point)
                        if gap_vector is None:
                            continue
                        gap_distance = math.hypot(
                            second_point.X - first_point.X, second_point.Y - first_point.Y
                        )
                        if gap_distance > maximum_gap:
                            continue
                        if (
                            abs(_dot_product(first_axis, gap_vector)) < minimum_axis_alignment
                            or abs(_dot_product(second_axis, gap_vector)) < minimum_axis_alignment
                        ):
                            continue
                        candidates.append((
                            gap_distance,
                            first_id,
                            first_end_index,
                            second_id,
                            second_end_index,
                            first_point,
                            second_point,
                            min(first_width, second_width),
                        ))

        arcpy.management.CreateFeatureclass(
            scratch_workspace,
            os.path.basename(output_connectors),
            "POLYGON",
            spatial_reference=spatial_reference,
        )
        used_endpoints = set()
        connector_count = 0
        with arcpy.da.InsertCursor(output_connectors, ["SHAPE@"]) as cursor:
            for (_, first_id, first_end_index, second_id, second_end_index,
                 first_point, second_point, width) in sorted(candidates):
                first_key = (first_id, first_end_index)
                second_key = (second_id, second_end_index)
                if first_key in used_endpoints or second_key in used_endpoints or width <= 0:
                    continue
                connection = arcpy.Polyline(
                    arcpy.Array([first_point, second_point]), spatial_reference
                ).buffer(width / 2.0)
                if connection and connection.getArea("GEODESIC", "SQUAREMETERS") > 0:
                    cursor.insertRow([connection])
                    used_endpoints.update((first_key, second_key))
                    connector_count += 1
        return connector_count
    finally:
        if arcpy.Exists(bounding_rectangles):
            arcpy.management.Delete(bounding_rectangles)


def _rectangle_road_endpoints(rectangle):
    if not rectangle or rectangle.partCount != 1:
        return None
    points = [point for point in rectangle.getPart(0) if point]
    if (
        len(points) > 1
        and points[0].X == points[-1].X
        and points[0].Y == points[-1].Y
    ):
        points.pop()
    if len(points) != 4:
        return None
    edges = []
    for index, point in enumerate(points):
        next_point = points[(index + 1) % len(points)]
        edges.append((math.hypot(next_point.X - point.X, next_point.Y - point.Y), point, next_point))
    short_edges = sorted(edges, key=lambda edge: edge[0])[:2]
    if not short_edges[0][0] or not short_edges[1][0]:
        return None
    endpoints = []
    for _, first_point, second_point in short_edges:
        endpoints.append(arcpy.Point(
            (first_point.X + second_point.X) / 2.0,
            (first_point.Y + second_point.Y) / 2.0,
        ))
    return endpoints[0], endpoints[1], (short_edges[0][0] + short_edges[1][0]) / 2.0


def _unit_vector(first_point, second_point):
    delta_x = second_point.X - first_point.X
    delta_y = second_point.Y - first_point.Y
    length = math.hypot(delta_x, delta_y)
    if not length:
        return None
    return delta_x / length, delta_y / length


def _dot_product(first_vector, second_vector):
    return first_vector[0] * second_vector[0] + first_vector[1] * second_vector[1]

def _regularize_building_footprints(
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
                tolerance=_meters_to_spatial_units(
                    tolerance_meters, spatial_reference
                ),
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
        if selected_count < 6:
            raise arcpy.ExecuteError(
                "Damage example points must intersect at least 6 unique target features; "
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


def _select_embedding_queries(
    embedding_features, sample_points, scratch_workspace, messages
):
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
        messages.addMessage(
            f"Using {selected_count} embedding cell(s) as similarity examples."
        )
        return query_features
    except Exception:
        if arcpy.Exists(query_features):
            arcpy.management.Delete(query_features)
        raise
    finally:
        if arcpy.Exists(embedding_layer):
            arcpy.management.Delete(embedding_layer)


def _select_feature_embedding_queries(
    embedding_features, target_features, sample_points, scratch_workspace, messages,
    class_value=None, is_road=False,
):
    if is_road:
        return _select_road_feature_embedding_queries(
            embedding_features, target_features, sample_points, scratch_workspace, messages,
            class_value,
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
            f"{class_label}: {point_count} example point(s) selected "
            f"{target_count} intersecting target feature(s)."
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


def _select_road_feature_embedding_queries(
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
        arcpy.management.SelectLayerByLocation(
            sample_layer, "WITHIN_A_DISTANCE", target_features, "10 Meters", "NEW_SELECTION"
        )
        sample_count = int(arcpy.management.GetCount(sample_layer)[0])
        if sample_count < 6:
            raise arcpy.ExecuteError(
                f"{class_label} needs at least 6 points on or within 10 meters of inferred roads; "
                f"{sample_count} valid point(s) remain."
            )
        arcpy.analysis.PairwiseBuffer(sample_layer, sample_regions, "10 Meters", dissolve_option="NONE")
        arcpy.management.MakeFeatureLayer(target_features, target_layer)
        arcpy.management.SelectLayerByLocation(target_layer, "INTERSECT", sample_regions, None, "NEW_SELECTION")
        arcpy.management.CopyFeatures(target_layer, seed_features)
        arcpy.management.MakeFeatureLayer(embedding_features, embedding_layer)
        arcpy.management.SelectLayerByLocation(embedding_layer, "INTERSECT", sample_regions, None, "NEW_SELECTION")
        cell_count = int(arcpy.management.GetCount(embedding_layer)[0])
        if cell_count < 6:
            raise arcpy.ExecuteError(
                f"{class_label} needs at least 6 intersecting embedding cells; {cell_count} cell(s) were selected."
            )
        arcpy.management.CopyFeatures(embedding_layer, query_features)
        messages.addMessage(
            f"{class_label}: using {sample_count} valid point-centered road region(s) and "
            f"{cell_count} embedding cell(s) as similarity examples."
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


def _create_road_damage_queries(
    target_features, sample_points, scratch_workspace, messages
):
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


def _recommend_grid_size(target_features, post_image, feature_type):
    profile_grid_size = FEATURE_PROFILES[feature_type]["embedding_grid_size"]
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
        return profile_grid_size
    median_width = statistics.median(widths)
    image_cell_size_meters = image_cell_size * image_meters_per_unit
    estimated_size = int(round((1.5 * median_width) / (16.0 * image_cell_size_meters)))
    return max(profile_grid_size, min(11, estimated_size))


def _create_debris_clusters(
    similar_features,
    output_features,
    scratch_workspace,
    messages,
):
    aggregated_features = arcpy.CreateUniqueName(
        "debris_similarity_aggregated", scratch_workspace
    )
    coverage_features = arcpy.CreateUniqueName(
        "debris_similarity_coverage", scratch_workspace
    )
    smoothed_features = arcpy.CreateUniqueName(
        "debris_similarity_smoothed", scratch_workspace
    )
    clustered_features = arcpy.CreateUniqueName(
        "debris_similarity_clusters", scratch_workspace
    )
    cluster_layer = arcpy.CreateUniqueName("debris_similarity_cluster_selection")

    try:
        aggregation_distance, minimum_hole_area = _debris_coverage_tolerance(
            similar_features
        )
        messages.addMessage(
            "Consolidating nearby debris similarity cells into coverage polygons..."
        )
        arcpy.cartography.AggregatePolygons(
            in_features=similar_features,
            out_feature_class=aggregated_features,
            aggregation_distance=aggregation_distance,
            minimum_area=0,
            minimum_hole_size=minimum_hole_area,
            orthogonality_option="NON_ORTHOGONAL",
        )
        arcpy.management.EliminatePolygonPart(
            aggregated_features,
            coverage_features,
            "AREA",
            minimum_hole_area,
            "0",
            "CONTAINED_ONLY",
        )
        arcpy.cartography.SmoothPolygon(
            in_features=coverage_features,
            out_feature_class=smoothed_features,
            algorithm="PAEK",
            tolerance=aggregation_distance,
            endpoint_option="FIXED_ENDPOINT",
            error_option="RESOLVE_ERRORS",
        )
        arcpy.analysis.SpatialJoin(
            target_features=smoothed_features,
            join_features=similar_features,
            out_feature_class=clustered_features,
            join_operation="JOIN_ONE_TO_ONE",
            join_type="KEEP_COMMON",
            match_option="INTERSECT",
        )
        arcpy.management.MakeFeatureLayer(clustered_features, cluster_layer)
        arcpy.management.SelectLayerByAttribute(
            cluster_layer,
            "NEW_SELECTION",
            "Join_Count >= 4",
        )
        cluster_count = int(arcpy.management.GetCount(cluster_layer)[0])
        arcpy.management.CopyFeatures(cluster_layer, output_features)
        removed_small_clusters = 0
        with arcpy.da.UpdateCursor(output_features, ["SHAPE@"]) as cursor:
            for (geometry,) in cursor:
                if (
                    not geometry
                    or geometry.getArea("GEODESIC", "SQUAREMETERS") < 4.0
                ):
                    cursor.deleteRow()
                    removed_small_clusters += 1
        cluster_count -= removed_small_clusters
        messages.addMessage(
            f"Created {cluster_count:,} debris polygon cluster(s) from matching "
            "embedding cells; sparse matches were excluded."
        )
        if removed_small_clusters:
            messages.addMessage(
                f"Excluded {removed_small_clusters:,} debris polygon(s) smaller "
                "than 4 square meters."
            )
    finally:
        for dataset in (
            aggregated_features,
            coverage_features,
            smoothed_features,
            clustered_features,
            cluster_layer,
        ):
            if arcpy.Exists(dataset):
                arcpy.management.Delete(dataset)


def _debris_coverage_tolerance(similar_features):
    cell_widths = []
    cell_areas = []
    with arcpy.da.SearchCursor(similar_features, ["SHAPE@"]) as cursor:
        for index, (geometry,) in enumerate(cursor):
            if geometry and geometry.pointCount > 0:
                extent = geometry.extent
                cell_width = max(extent.width, extent.height)
                cell_area = geometry.area
                if cell_width > 0 and cell_area > 0:
                    cell_widths.append(cell_width)
                    cell_areas.append(cell_area)
            if index >= 4999:
                break
    if not cell_widths or not cell_areas:
        raise arcpy.ExecuteError(
            "Similar debris embedding features must contain valid polygon cells."
        )
    cell_width = statistics.median(cell_widths)
    return cell_width * 0.5, statistics.median(cell_areas) * 2.0


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
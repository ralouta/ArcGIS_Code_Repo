import os


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
        "embedding_grid_size": 3,
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
        "road_mask_simplification_m": 5.0,
        "road_minimum_part_area_sqm": 50.0,
        "road_centerline_extension_m": 25.0,
        "road_centerline_simplification_m": 5.0,
        "road_minimum_half_width_m": 2.5,
        "road_maximum_half_width_m": 10.0,
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
        "embedding_grid_size": 3,
        "regularize": False,
        "feature_code": "AGRICULTURAL_COVER_CANDIDATE",
        "production_geometry": "Polygon",
        "minimum_area_sqm": 100.0,
        "maximum_gsd_m": 0.5,
        "nms_overlap": 0.6,
        "field_contraction_m": 10.0,
        "field_minimum_area_sqm": 500.0,
        "field_hole_fill_sqm": 1000.0,
        "field_part_area_percent": 20.0,
        "field_boundary_simplification_m": 8.0,
        "field_boundary_smoothing_m": 5.0,
        "field_parent_min_children": 2,
        "field_parent_min_coverage": 0.85,
        "field_parent_max_coverage": 1.0,
        "field_parent_max_child_area_ratio": 0.75,
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

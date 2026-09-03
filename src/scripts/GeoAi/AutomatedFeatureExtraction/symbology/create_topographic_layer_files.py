"""Create portable ArcGIS Pro layer files for Automated Feature Extraction outputs.

Run this script with the ArcGIS Pro Python environment. It uses an existing polygon
feature class only as a temporary schema source; the resulting layer files can be
repointed to any compatible toolbox output in ArcGIS Pro.
"""

import os

import arcpy


LAYER_STYLES = {
    "Buildings": ((194, 162, 120, 65), (99, 77, 52, 100), 0.8),
    "Bridges": ((171, 139, 103, 60), (85, 65, 45, 100), 1.2),
    "Roads": ((216, 210, 196, 55), (137, 133, 123, 100), 0.7),
    "Water Bodies": ((95, 166, 214, 55), (42, 111, 158, 100), 0.8),
    "Rail Corridors": ((105, 97, 88, 45), (59, 54, 49, 100), 1.0),
    "Impervious Surfaces": ((190, 187, 177, 50), (126, 124, 117, 100), 0.6),
    "Parking Areas": ((180, 178, 169, 45), (112, 111, 104, 100), 0.6),
    "Solar Arrays": ((75, 105, 130, 55), (34, 61, 85, 100), 0.7),
    "Sports Surfaces": ((151, 188, 105, 50), (72, 124, 65, 100), 0.8),
    "Swimming Pools": ((52, 157, 214, 65), (19, 103, 157, 100), 0.8),
    "Construction Areas": ((203, 145, 62, 45), (143, 91, 30, 100), 0.8),
    "Material Stockpiles": ((183, 132, 78, 50), (122, 78, 38, 100), 0.8),
    "Bare Ground": ((216, 195, 148, 45), (158, 133, 84, 100), 0.7),
    "Flooded Areas": ((79, 146, 201, 40), (31, 95, 150, 100), 0.8),
    "Debris": ((153, 96, 81, 45), (104, 53, 43, 100), 0.8),
    "Vehicles": ((83, 88, 91, 60), (36, 40, 42, 100), 0.6),
    "Trees": ((71, 139, 77, 45), (35, 98, 48, 100), 0.7),
    "Forest Cover": ((104, 153, 82, 35), (55, 105, 55, 100), 0.7),
    "Agricultural Fields": ((176, 190, 99, 35), (112, 132, 59, 100), 0.8),
    "Park-Like Green Space": ((126, 173, 107, 35), (62, 118, 67, 100), 0.7),
    "Utility Poles": ((88, 95, 94, 45), (35, 42, 41, 100), 0.8),
    "Other Structures": ((163, 139, 113, 55), (96, 73, 51, 100), 0.8),
    "Custom": ((160, 150, 160, 35), (97, 83, 97, 100), 0.8),
}


def create_layer_files(template_features, output_directory):
    """Save one simple-renderer layer file for every supported profile."""
    template_description = arcpy.Describe(template_features)
    if template_description.shapeType != "Polygon":
        raise ValueError("Template Features must be a polygon feature class or layer.")
    template_path = template_description.catalogPath

    os.makedirs(output_directory, exist_ok=True)
    project = arcpy.mp.ArcGISProject("CURRENT")
    active_map = project.activeMap
    if active_map is None:
        raise RuntimeError("Open a map in ArcGIS Pro before running this script.")

    for feature_type, (fill_color, outline_color, outline_width) in LAYER_STYLES.items():
        layer = active_map.addDataFromPath(template_path)
        try:
            layer.name = feature_type
            symbology = layer.symbology
            symbology.updateRenderer("SimpleRenderer")
            symbol = symbology.renderer.symbol
            symbol.color = {"RGB": list(fill_color)}
            symbol.outlineColor = {"RGB": list(outline_color)}
            symbol.outlineWidth = outline_width
            layer.symbology = symbology
            output_file = os.path.join(
                output_directory, f"{feature_type.replace(' ', '_')}.lyrx"
            )
            layer.saveACopy(output_file)
            arcpy.AddMessage(f"Created {output_file}")
        finally:
            active_map.removeLayer(layer)


if __name__ == "__main__":
    create_layer_files(
        arcpy.GetParameterAsText(0),
        arcpy.GetParameterAsText(1) or os.path.dirname(__file__),
    )
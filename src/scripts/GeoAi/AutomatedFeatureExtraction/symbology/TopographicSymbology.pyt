import os

import arcpy

from create_topographic_layer_files import create_layer_files


class Toolbox:
    def __init__(self):
        self.label = "Automated Feature Extraction Symbology"
        self.alias = "afe_symbology"
        self.tools = [CreateTopographicLayerFiles]


class CreateTopographicLayerFiles:
    def __init__(self):
        self.label = "Create Topographic Layer Files"
        self.description = (
            "Creates a reusable ArcGIS Pro layer file for every Automated Feature "
            "Extraction profile."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        template_features = arcpy.Parameter(
            displayName="Template Polygon Features",
            name="template_features",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        template_features.filter.list = ["Polygon"]
        road_template_features = arcpy.Parameter(
            displayName="Template Road Centerline Features",
            name="road_template_features",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        road_template_features.filter.list = ["Polyline"]
        output_directory = arcpy.Parameter(
            displayName="Output Symbology Folder",
            name="output_directory",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input",
        )
        output_directory.value = os.path.dirname(__file__)
        return [template_features, road_template_features, output_directory]

    def execute(self, parameters, messages):
        output_directory = parameters[2].valueAsText
        messages.addMessage(f"Creating topographic layer files in {output_directory}...")
        create_layer_files(
            parameters[0].valueAsText, parameters[1].valueAsText, output_directory
        )
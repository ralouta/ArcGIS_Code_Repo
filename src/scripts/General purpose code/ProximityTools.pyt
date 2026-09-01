import arcpy
import uuid


class Toolbox(object):
    def __init__(self):
        self.label = "Proximity Tools"
        self.alias = "proximitytools"
        self.description = "Generic geoprocessing tasks for proximity analysis."
        self.tools = [FindFeaturesNearFeatures]


class FindFeaturesNearFeatures(object):
    def __init__(self):
        self.label = "Find Features Near Features"
        self.description = (
            "Selects input features that are within a specified geodesic distance "
            "of one or more proximity features and writes the selected features "
            "to a new feature class."
        )

    def getParameterInfo(self):
        input_features = arcpy.Parameter(
            displayName="Input Features",
            name="in_features",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        input_features.description = (
            "The features to evaluate for proximity. Example: a layer of reported "
            "safety issues, addresses, or assets."
        )

        proximity_features = arcpy.Parameter(
            displayName="Proximity Features",
            name="proximity_features",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        proximity_features.description = (
            "The reference features used to find nearby input features. Example: "
            "schools, evacuation routes, inspection areas, or a selected point."
        )

        search_distance = arcpy.Parameter(
            displayName="Search Distance",
            name="search_distance",
            datatype="GPLinearUnit",
            parameterType="Required",
            direction="Input",
        )
        search_distance.description = (
            "The geodesic distance used to select input features near the proximity "
            "features. Example: 500 Meters or 2 Miles."
        )

        output_features = arcpy.Parameter(
            displayName="Output Features",
            name="out_features",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Output",
        )
        output_features.description = (
            "The output feature class containing input features within the specified "
            "distance. Example: C:\\data\\analysis.gdb\\issues_near_schools."
        )

        return [input_features, proximity_features, search_distance, output_features]

    def execute(self, parameters, messages):
        in_features = parameters[0].valueAsText
        proximity_features = parameters[1].valueAsText
        search_distance = parameters[2].valueAsText
        out_features = parameters[3].valueAsText
        layer_name = "proximity_candidates_{}".format(uuid.uuid4().hex)

        try:
            arcpy.management.MakeFeatureLayer(in_features, layer_name)
            result = arcpy.management.SelectLayerByLocation(
                layer_name,
                "WITHIN_A_DISTANCE_GEODESIC",
                proximity_features,
                search_distance,
                "NEW_SELECTION",
            )
            selected_count = int(result.getOutput(1))
            arcpy.management.CopyFeatures(layer_name, out_features)
            arcpy.AddMessage(
                "Created {} with {} feature(s) within {} of the proximity features.".format(
                    out_features, selected_count, search_distance
                )
            )
        finally:
            if arcpy.Exists(layer_name):
                arcpy.management.Delete(layer_name)

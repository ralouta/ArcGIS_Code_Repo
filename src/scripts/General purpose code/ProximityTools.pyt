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

        input_where_clause = arcpy.Parameter(
            displayName="Input Features Where Clause",
            name="input_where_clause",
            datatype="GPSQLExpression",
            parameterType="Optional",
            direction="Input",
        )
        input_where_clause.parameterDependencies = [input_features.name]
        input_where_clause.description = (
            "Optional SQL expression used to filter the input features before "
            "proximity analysis. Example: country = 'Saudi Arabia'."
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

        proximity_where_clause = arcpy.Parameter(
            displayName="Proximity Features Where Clause",
            name="proximity_where_clause",
            datatype="GPSQLExpression",
            parameterType="Optional",
            direction="Input",
        )
        proximity_where_clause.parameterDependencies = [proximity_features.name]
        proximity_where_clause.description = (
            "Optional SQL expression used to filter the proximity features before "
            "analysis. Example: country = 'Saudi Arabia'."
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
            datatype="GPFeatureRecordSetLayer",
            parameterType="Required",
            direction="Output",
        )
        output_features.description = (
            "The output feature class containing input features within the specified "
            "distance. Example: C:\\data\\analysis.gdb\\issues_near_schools."
        )

        return [
            input_features,
            input_where_clause,
            proximity_features,
            proximity_where_clause,
            search_distance,
            output_features,
        ]

    def execute(self, parameters, messages):
        in_features = parameters[0].valueAsText
        input_where_clause = parameters[1].valueAsText
        proximity_features = parameters[2].valueAsText
        proximity_where_clause = parameters[3].valueAsText
        search_distance = parameters[4].valueAsText
        out_features = parameters[5].valueAsText
        input_layer_name = "proximity_candidates_{}".format(uuid.uuid4().hex)
        proximity_layer_name = "proximity_features_{}".format(uuid.uuid4().hex)

        try:
            arcpy.management.MakeFeatureLayer(
                in_features, input_layer_name, input_where_clause
            )
            arcpy.management.MakeFeatureLayer(
                proximity_features, proximity_layer_name, proximity_where_clause
            )
            arcpy.management.SelectLayerByLocation(
                input_layer_name,
                "WITHIN_A_DISTANCE_GEODESIC",
                proximity_layer_name,
                search_distance,
                "NEW_SELECTION",
            )
            selected_count = int(arcpy.management.GetCount(input_layer_name)[0])
            arcpy.management.CopyFeatures(input_layer_name, out_features)
            arcpy.AddMessage(
                "Created {} with {} feature(s) within {} of the proximity features.".format(
                    out_features, selected_count, search_distance
                )
            )
        finally:
            for layer_name in [input_layer_name, proximity_layer_name]:
                if arcpy.Exists(layer_name):
                    arcpy.management.Delete(layer_name)

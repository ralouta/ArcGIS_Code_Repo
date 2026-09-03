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
            "Returns input features within a specified geodesic distance of "
            "reference features. Before supplying either optional SQL filter, "
            "inspect that layer's schema and use its physical field names and "
            "verified values, not display aliases. Use the SQL dialect accepted "
            "by the referenced feature service."
        )

    def getParameterInfo(self):
        input_features = arcpy.Parameter(
            displayName="Input Features",
            name="in_features",
            datatype="GPFeatureRecordSetLayer",
            parameterType="Required",
            direction="Input",
        )
        input_features.description = (
            "The features to evaluate for proximity. For REST requests, provide a "
            "layer object with a url property, for example {\"url\": "
            "\"https://.../FeatureServer/0\"}."
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
            "Optional SQL expression used to filter input features before proximity "
            "analysis. Use a physical field name from the input layer schema, not a "
            "field alias, and a verified value. For example, DAMAGE_CLASS = 'High "
            "Damage Evidence' only when DAMAGE_CLASS and that value exist in the "
            "selected layer. Leave blank to evaluate all input features."
        )

        proximity_features = arcpy.Parameter(
            displayName="Proximity Features",
            name="proximity_features",
            datatype="GPFeatureRecordSetLayer",
            parameterType="Required",
            direction="Input",
        )
        proximity_features.description = (
            "The reference features used to find nearby input features. For REST "
            "requests, provide a layer object with a url property, for example "
            "{\"url\": \"https://.../FeatureServer/0\"}."
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
            "Optional SQL expression used to filter proximity features before "
            "analysis. Use a physical field name from the proximity layer schema, "
            "not a field alias, and a verified value. For example, DAMAGE_CLASS = "
            "'High Damage Evidence' only when DAMAGE_CLASS and that value exist in "
            "the selected layer. Leave blank to use all proximity features."
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

    @staticmethod
    def _optional_where_clause(parameter):
        value = parameter.valueAsText
        if value is None:
            return None
        value = value.strip()
        if value.lower() in ("", "#", "none", "null"):
            return None
        return value

    def execute(self, parameters, messages):
        in_features = parameters[0].value
        input_where_clause = self._optional_where_clause(parameters[1])
        proximity_features = parameters[2].value
        proximity_where_clause = self._optional_where_clause(parameters[3])
        search_distance = parameters[4].valueAsText
        out_features = parameters[5].valueAsText
        input_layer_name = "proximity_candidates_{}".format(uuid.uuid4().hex)
        proximity_layer_name = "proximity_features_{}".format(uuid.uuid4().hex)

        try:
            input_layer_args = [in_features, input_layer_name]
            if input_where_clause:
                input_layer_args.append(input_where_clause)
            arcpy.AddMessage(
                "Input features where clause: {}".format(
                    input_where_clause or "<none>"
                )
            )
            arcpy.management.MakeFeatureLayer(*input_layer_args)

            proximity_layer_args = [proximity_features, proximity_layer_name]
            if proximity_where_clause:
                proximity_layer_args.append(proximity_where_clause)
            arcpy.AddMessage(
                "Proximity features where clause: {}".format(
                    proximity_where_clause or "<none>"
                )
            )
            arcpy.management.MakeFeatureLayer(*proximity_layer_args)
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

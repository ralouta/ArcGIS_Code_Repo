import arcpy
import json
import os
import tempfile
import uuid
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import urlopen


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
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        input_features.description = (
            "The features to evaluate for proximity. For REST requests, provide a "
            "feature layer URL, for example https://.../FeatureServer/0."
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
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        proximity_features.description = (
            "The reference features used to find nearby input features. For REST "
            "requests, provide a feature layer URL, for example "
            "https://.../FeatureServer/0."
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
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Output",
        )
        output_features.description = (
            "A new feature class containing input features within the specified "
            "distance. Example: C:\\data\\analysis.gdb\\issues_near_schools."
        )

        selected_feature_count = arcpy.Parameter(
            displayName="Selected Feature Count",
            name="selected_feature_count",
            datatype="GPLong",
            parameterType="Derived",
            direction="Output",
        )
        selected_feature_count.description = (
            "The number of input features within the specified distance of the "
            "filtered proximity features."
        )

        return [
            input_features,
            input_where_clause,
            proximity_features,
            proximity_where_clause,
            search_distance,
            output_features,
            selected_feature_count,
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

    @staticmethod
    def _is_feature_service_url(value):
        parsed_url = urlparse(value)
        return (
            parsed_url.scheme in ("http", "https")
            and "/featureserver/" in parsed_url.path.lower()
        )

    @staticmethod
    def _feature_service_request(layer_url, parameters):
        parsed_url = urlparse(layer_url)
        query_parameters = dict(parse_qsl(parsed_url.query, keep_blank_values=True))
        query_parameters.update(parameters)
        request_url = urlunparse(
            (
                parsed_url.scheme,
                parsed_url.netloc,
                parsed_url.path.rstrip("/") + "/query",
                "",
                urlencode(query_parameters),
                "",
            )
        )
        with urlopen(request_url) as response:
            result = json.load(response)
        if "error" in result:
            raise RuntimeError(result["error"].get("message", "Feature service query failed."))
        return result

    @classmethod
    def _feature_service_to_feature_class(cls, layer_url, where_clause, name):
        query_parameters = {
            "f": "json",
            "where": where_clause or "1=1",
            "returnIdsOnly": "true",
        }
        object_id_response = cls._feature_service_request(layer_url, query_parameters)
        object_ids = object_id_response.get("objectIds", [])
        scratch_gdb = arcpy.env.scratchGDB
        output_feature_class = arcpy.CreateUniqueName(name, scratch_gdb)

        feature_collection = None
        for start_index in range(0, len(object_ids), 500):
            feature_response = cls._feature_service_request(
                layer_url,
                {
                    "f": "json",
                    "objectIds": ",".join(
                        str(object_id)
                        for object_id in object_ids[start_index : start_index + 500]
                    ),
                    "outFields": "*",
                    "returnGeometry": "true",
                },
            )
            if feature_collection is None:
                feature_collection = feature_response
            else:
                feature_collection["features"].extend(feature_response.get("features", []))

        if feature_collection is None:
            feature_collection = cls._feature_service_request(
                layer_url,
                {
                    "f": "json",
                    "where": "1=0",
                    "outFields": "*",
                    "returnGeometry": "true",
                },
            )

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as json_file:
            json.dump(feature_collection, json_file)
            json_file_path = json_file.name

        try:
            arcpy.conversion.JSONToFeatures(json_file_path, output_feature_class)
        finally:
            os.remove(json_file_path)

        return output_feature_class

    @classmethod
    def _make_input_layer(cls, source, where_clause, layer_name):
        if cls._is_feature_service_url(source):
            feature_class = cls._feature_service_to_feature_class(
                source, where_clause, layer_name
            )
            arcpy.management.MakeFeatureLayer(feature_class, layer_name)
            return feature_class

        layer_args = [source, layer_name]
        if where_clause:
            layer_args.append(where_clause)
        arcpy.management.MakeFeatureLayer(*layer_args)
        return None

    def execute(self, parameters, messages):
        in_features = parameters[0].valueAsText
        input_where_clause = self._optional_where_clause(parameters[1])
        proximity_features = parameters[2].valueAsText
        proximity_where_clause = self._optional_where_clause(parameters[3])
        search_distance = parameters[4].valueAsText
        out_features = parameters[5].valueAsText
        input_layer_name = "proximity_candidates_{}".format(uuid.uuid4().hex)
        proximity_layer_name = "proximity_features_{}".format(uuid.uuid4().hex)
        temporary_feature_classes = []

        try:
            arcpy.AddMessage(
                "Input features where clause: {}".format(
                    input_where_clause or "<none>"
                )
            )
            input_feature_class = self._make_input_layer(
                in_features, input_where_clause, input_layer_name
            )
            if input_feature_class:
                temporary_feature_classes.append(input_feature_class)

            arcpy.AddMessage(
                "Proximity features where clause: {}".format(
                    proximity_where_clause or "<none>"
                )
            )
            proximity_feature_class = self._make_input_layer(
                proximity_features, proximity_where_clause, proximity_layer_name
            )
            if proximity_feature_class:
                temporary_feature_classes.append(proximity_feature_class)
            arcpy.management.SelectLayerByLocation(
                input_layer_name,
                "WITHIN_A_DISTANCE_GEODESIC",
                proximity_layer_name,
                search_distance,
                "NEW_SELECTION",
            )
            selected_count = int(arcpy.management.GetCount(input_layer_name)[0])
            arcpy.management.CopyFeatures(input_layer_name, out_features)
            parameters[6].value = selected_count
            arcpy.AddMessage(
                "Created {} with {} feature(s) within {} of the proximity features.".format(
                    out_features, selected_count, search_distance
                )
            )
        finally:
            for layer_name in [input_layer_name, proximity_layer_name]:
                if arcpy.Exists(layer_name):
                    arcpy.management.Delete(layer_name)
            for feature_class in temporary_feature_classes:
                if arcpy.Exists(feature_class):
                    arcpy.management.Delete(feature_class)

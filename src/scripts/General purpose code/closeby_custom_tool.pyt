import arcpy
import os

"""
The Closeby Custom Tool is a Python toolbox for ArcGIS designed to aggregate points
based on their proximity to a central point. It calculates the distances of all points
from a specified central point, selects a user-defined percentage of the closest points,
and then creates a convex hull polygon around these selected points.

This tool is useful for spatial analyses where understanding the area covered
by the nearest points to a location is necessary. It leverages ArcPy,
a Python site-package that provides a useful and productive way to perform
geographic data analysis, data conversion, data management, and map automation
with Python.

This toolbox contains a single tool, `ClosebyCustomTool`, which implements
the described functionality through its `execute` method. Parameters for the
tool include the input points layer, a field in the layer to identify points,
the ID of the central point, the percentage of points to include, and the
output location for the generated polygon.
"""


class Toolbox(object):
    def __init__(self):
        """Define the toolbox (the name of the toolbox is the name of the .pyt file)."""
        self.label = "Closeby Custom Tool"
        self.alias = "Closeby Custom Tool"

        # List of tool classes associated with this toolbox
        self.tools = [ClosebyCustomTool]

class ClosebyCustomTool(object):
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "Aggregate Closeby Points"
        self.description = "Aggregates a percentage of points closest to a central point into a polygon."
    
    def getParameterInfo(self):
        """Define parameter definitions"""
        params = [arcpy.Parameter(displayName="Input Points",
                                  name="in_points",
                                  datatype="GPFeatureLayer",
                                  parameterType="Required",
                                  direction="Input"),
                  arcpy.Parameter(displayName="Point ID Field",
                                  name="point_id_field",
                                  datatype="Field",
                                  parameterType="Required",
                                  direction="Input"),
                  arcpy.Parameter(displayName="Central Point ID",
                                  name="central_point_id",
                                  datatype="GPString",
                                  parameterType="Required",
                                  direction="Input"),
                  arcpy.Parameter(displayName="Percentage of Points to Include",
                                  name="percentage",
                                  datatype="GPLong",
                                  parameterType="Required",
                                  direction="Input"),
                  arcpy.Parameter(displayName="Output Polygon",
                                  name="out_polygon",
                                  datatype="DEFeatureClass",
                                  parameterType="Required",
                                  direction="Output")]
        params[1].parameterDependencies = [params[0].name]  # Point ID Field depends on Input Points
        params[1].filter.list = ['Short', 'Long', 'Double', 'Integer', 'String']  # Filter for suitable field types
        return params

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal validation is performed."""
        if parameters[0].altered:
            # When the input points layer is changed, update the list of fields for the Point ID Field parameter
            layer = parameters[0].value  # Get the selected feature layer
            if layer:
                fields = arcpy.ListFields(layer)
                parameters[1].filter.list = [field.name for field in fields if field.type in ('Integer', 'String', 'OID', 'GUID')]
        return

    def execute(self, parameters, messages):
        """The source code of the tool."""
        in_points = parameters[0].valueAsText
        point_id_field = parameters[1].valueAsText
        central_point_id = parameters[2].valueAsText
        percentage = int(parameters[3].value)
        out_polygon = parameters[4].valueAsText

        arcpy.env.workspace = arcpy.Describe(in_points).path

        # Find the central point coordinates
        central_point_feature = arcpy.da.SearchCursor(in_points, ["SHAPE@XY"], f'"{point_id_field}" = {central_point_id}')
        central_point_corrdinates = [row[0] for row in central_point_feature]
        arcpy.AddMessage(f"Central point feature: {central_point_corrdinates}")
        central_point = arcpy.Point(*central_point_feature)

        # Calculate distances from each point to the central point
        with arcpy.da.SearchCursor(in_points, ["SHAPE@XY"]) as cursor:
            distances = [(row[0], arcpy.PointGeometry(arcpy.Point(*row[0])).distanceTo(arcpy.PointGeometry(central_point))) for row in cursor]

        # Sort points by distance
        distances.sort(key=lambda x: x[1])

        # Select a percentage of the closest points
        count_to_select = int(len(distances) * (percentage / 100.0))
        selected_points = [x[0] for x in distances[:count_to_select]]

        # Create a convex hull (polygon) around the selected points
        selected_points_geometry = [arcpy.PointGeometry(arcpy.Point(*pt)) for pt in selected_points]
        convex_hull_polygon = arcpy.MinimumBoundingGeometry_management(selected_points_geometry, out_polygon, "CONVEX_HULL")[0]

        arcpy.AddMessage(f"Convex hull polygon created: {convex_hull_polygon}")
        
        return
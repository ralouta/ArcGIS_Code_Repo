import arcpy

class Toolbox(object):
    def __init__(self):
        self.label = "Map Cleanup Toolbox"
        self.alias = "MapCleanup"

        # List of tool classes associated with this toolbox
        self.tools = [CleanupTool]

class CleanupTool(object):
    def __init__(self):
        self.label = "Cleanup Tool"
        self.description = "Deletes all features in a geodatabase that are not in a map"
        self.canRunInBackground = False

    def getParameterInfo(self):
        params = [arcpy.Parameter(
                      displayName="Input Map",
                      name="in_map",
                      datatype="GPMap",
                      parameterType="Required",
                      direction="Input"),
                  arcpy.Parameter(
                      displayName="Input Geodatabase",
                      name="in_gdb",
                      datatype="DEWorkspace",
                      parameterType="Required",
                      direction="Input")]
        return params

    def execute(self, parameters, messages):
        map_name = parameters[0].valueAsText
        geodatabase = parameters[1].valueAsText

        # Get a reference to the current ArcGIS project
        aprx = arcpy.mp.ArcGISProject('current')

        # Get the specified map from the project
        map = next((m for m in aprx.listMaps() if m.name == map_name), None)
        if map is None:
            arcpy.AddError(f"No map named '{map_name}' found in the current project.")
            return

        # Get the list of all layers in the map
        map_layers = [layer.name for layer in map.listLayers()]
        
        _ = [arcpy.AddMessage(f"Layer: {layer}") for layer in map_layers]        
        
        # Set the workspace to the input geodatabase
        arcpy.env.workspace = geodatabase

        # Set the workspace to the input geodatabase
        arcpy.env.workspace = geodatabase

        # List all feature classes, tables, and rasters in the geodatabase
        feature_classes = arcpy.ListFeatureClasses()
        tables = arcpy.ListTables()
        rasters = arcpy.ListRasters()

        # Combine all data types into one list
        all_data = feature_classes + tables + rasters

        # Delete data types that are not in the map
        for data in all_data:
            if data not in map_layers:
                arcpy.AddMessage(f"Deleting {data}...")
                arcpy.Delete_management(data)
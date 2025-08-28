import arcpy
import os
import re
import json

class RasterToPolygonTool(object):
    def __init__(self):
        self.label = "Raster to Polygon Landcover Extraction"
        self.description = "Converts all rasters in a folder to polygons, assigns landcover classes, and merges them."
        self.canRunInBackground = False

    def getParameterInfo(self):
        params = []
        # Input folder
        param0 = arcpy.Parameter(
            displayName="Input Folder",
            name="input_folder",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input"
        )
        # Output feature class
        param1 = arcpy.Parameter(
            displayName="Output Feature Class",
            name="output_fc",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Output"
        )
        params.append(param0)
        params.append(param1)
        return params

    def execute(self, parameters, messages):
        input_folder = parameters[0].valueAsText
        output_fc = parameters[1].valueAsText

        arcpy.AddMessage(f"Starting LandCoverExtraction tool...")

        # Find .lyrx file
        arcpy.AddMessage("Searching for .lyrx file in input folder...")
        lyrx_file = None
        for f in os.listdir(input_folder):
            if f.lower().endswith('.lyrx'):
                lyrx_file = os.path.join(input_folder, f)
                break
        if not lyrx_file:
            arcpy.AddError("No .lyrx file found in input folder.")
            raise Exception("No .lyrx file found in input folder.")

        arcpy.AddMessage(f"Found .lyrx file: {lyrx_file}")

        # Parse .lyrx for gridcode-class mapping
        arcpy.AddMessage("Parsing .lyrx file for gridcode-class mapping...")
        with open(lyrx_file, 'r') as f:
            lyrx_json = json.load(f)
        class_dict = {}
        groups = lyrx_json['layerDefinitions'][0]['colorizer']['groups']
        for group in groups:
            for cls in group['classes']:
                for val in cls['values']:
                    class_dict[int(val)] = cls['label']
        arcpy.AddMessage(f"Parsed {len(class_dict)} landcover classes from .lyrx file.")

        # Find all .tif files
        arcpy.AddMessage("Searching for .tif raster files in input folder...")
        tif_files = [f for f in os.listdir(input_folder) if f.lower().endswith('.tif')]
        arcpy.AddMessage(f"Found {len(tif_files)} raster files.")
        polys = []
        for i, tif in enumerate(tif_files, 1):
            tif_path = os.path.join(input_folder, tif)
            tif_base = os.path.splitext(os.path.basename(tif))[0]
            poly_name = f"poly_{tif_base}"
            poly_mem = f"in_memory/{poly_name}"
            arcpy.AddMessage(f"[{i}/{len(tif_files)}] Converting raster {tif} to polygon...")
            arcpy.conversion.RasterToPolygon(tif_path, poly_mem, "NO_SIMPLIFY", "Value")
            m = re.match(r"(\d{4})_(\d{2})_(D[123])", tif_base)
            if not m:
                arcpy.AddError(f"Tif name {tif_base} does not match expected format.")
                raise Exception(f"Tif name {tif_base} does not match expected format.")
            year, month, dekad = m.groups()
            dekad_day = {'D1': '01', 'D2': '10', 'D3': '20'}[dekad]
            date_str = f"{year}-{month}-{dekad_day}"
            arcpy.AddMessage(f"Adding date field ({date_str}) to polygons...")
            arcpy.management.AddField(poly_mem, "Date", "DATE")
            with arcpy.da.UpdateCursor(poly_mem, ["Date"]) as cursor:
                for row in cursor:
                    row[0] = date_str
                    cursor.updateRow(row)
            arcpy.AddMessage("Removing polygons smaller than 3600 sq meters...")
            with arcpy.da.UpdateCursor(poly_mem, ["SHAPE@AREA"]) as cursor:
                for row in cursor:
                    if row[0] < 3600:
                        cursor.deleteRow()
            arcpy.AddMessage("Simplifying polygons...")
            simp_mem = f"in_memory/simp_{poly_name}"
            arcpy.cartography.SimplifyPolygon(poly_mem, simp_mem, "POINT_REMOVE", "60 Meters")
            polys.append(simp_mem)
        arcpy.AddMessage("Merging all polygons together...")
        merged_mem = "in_memory/merged_polys"
        arcpy.management.Merge(polys, merged_mem)
        arcpy.AddMessage("Repairing geometry...")
        arcpy.management.RepairGeometry(merged_mem)
        arcpy.AddMessage("Adding and calculating class field...")
        arcpy.management.AddField(merged_mem, "Class", "TEXT")
        with arcpy.da.UpdateCursor(merged_mem, ["gridcode", "Class"]) as cursor:
            for row in cursor:
                row[1] = class_dict.get(row[0], "Unknown")
                cursor.updateRow(row)
        arcpy.AddMessage(f"Saving output to {output_fc}...")
        arcpy.management.CopyFeatures(merged_mem, output_fc)
        arcpy.AddMessage("LandCoverExtraction tool completed successfully.")

class Toolbox(object):
    def __init__(self):
        self.label = "LandCoverExtraction Toolbox"
        self.alias = "LandCoverExtraction"
        self.tools = [RasterToPolygonTool]

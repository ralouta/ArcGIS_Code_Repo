import arcpy
import os
import re
import json
import uuid

class Toolbox(object):
    def __init__(self):
        self.label = "LandCoverExtraction Toolbox"
        self.alias = "LandCoverExtraction"
        self.tools = [RasterToPolygonTool, SpatialJoinDivideTool]

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
            # Sanitize name for in_memory workspace: remove invalid chars (hyphens, periods, etc.)
            sanitized_base = re.sub(r'[^A-Za-z0-9_]+', '_', tif_base)
            sanitized_base = re.sub(r'_+', '_', sanitized_base).strip('_')
            if re.match(r'^\d', sanitized_base):
                sanitized_base = f"r_{sanitized_base}"  # cannot start with number
            # Limit length to avoid name length issues
            if len(sanitized_base) > 60:
                original = sanitized_base
                sanitized_base = sanitized_base[:60]
                arcpy.AddMessage(f"Truncated long name: {original} -> {sanitized_base}")
            if sanitized_base != tif_base:
                arcpy.AddMessage(f"Sanitized raster base name: {tif_base} -> {sanitized_base}")
            poly_name = f"poly_{sanitized_base}"
            poly_mem = f"in_memory/{poly_name}"
            arcpy.AddMessage(f"[{i}/{len(tif_files)}] Converting raster {tif} to polygon...")
            arcpy.conversion.RasterToPolygon(tif_path, poly_mem, "NO_SIMPLIFY", "Value")
            # Match final date pattern segment e.g. 2020-11-D1 at end of name
            m = re.search(r"(\d{4})-(\d{2})-(D[123])$", tif_base)
            if not m:
                arcpy.AddError(f"TIF name '{tif_base}' does not end with expected pattern YYYY-MM-D[1-3].")
                raise Exception(f"TIF name '{tif_base}' does not match expected format '...YYYY-MM-D[1-3]'.")
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
        polys = list(dict.fromkeys(polys))
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

class SpatialJoinDivideTool(object):
    def __init__(self):
        self.label = "Spatial Join & Divide Locations by Landcover"
        self.description = ("Spatially joins time-enabled landcover polygons to locations. "
                            "Subdivides locations if overlapping multiple landcover uses per time stamp.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        params = []
        param0 = arcpy.Parameter(displayName="Locations Feature Layer", name="locations_fc", datatype="GPFeatureLayer", parameterType="Required", direction="Input")
        param1 = arcpy.Parameter(displayName="Time-enabled Landcover Polygon Layer", name="landcover_fc", datatype="GPFeatureLayer", parameterType="Required", direction="Input")
        param2 = arcpy.Parameter(displayName="Location ID Field", name="location_id_field", datatype="Field", parameterType="Required", direction="Input")
        param2.parameterDependencies = ["locations_fc"]
        param2.filter.list = ["String", "Integer", "SmallInteger"]
        param3 = arcpy.Parameter(displayName="Output Feature Class", name="output_fc", datatype="DEFeatureClass", parameterType="Required", direction="Output")
        param4 = arcpy.Parameter(displayName="Batch Size (locations per chunk)", name="batch_size", datatype="Long", parameterType="Optional", direction="Input")
        param4.value = 500
        param5 = arcpy.Parameter(displayName="Keep Intermediates (Debug)", name="keep_intermediates", datatype="Boolean", parameterType="Optional", direction="Input")
        param5.value = False
        params.extend([param0, param1, param2, param3, param4, param5])
        return params
    
    def updateParameters(self, parameters):
        # Nothing dynamic needed for now: field picker handled by parameterDependencies.
        # (Left here for future enhancements such as filtering field types dynamically.)
        return
    
    def execute(self, parameters, messages):
        locations_fc = parameters[0].valueAsText
        landcover_fc = parameters[1].valueAsText
        location_id_field = parameters[2].valueAsText
        output_fc = parameters[3].valueAsText
        batch_size = int(parameters[4].value) if parameters[4].value else 500
        keep_intermediates = bool(parameters[5].value)

        loc_fields = [f.name for f in arcpy.ListFields(locations_fc)]
        if location_id_field not in loc_fields:
            raise arcpy.ExecuteError(f"Location ID field '{location_id_field}' not found in locations layer. Available: {loc_fields}")

        arcpy.AddMessage("Starting SpatialJoinDivideTool (optimized batch mode)...")
        arcpy.AddMessage(f"Batch size: {batch_size}")

        loc_layer = "_loc_layer_tmp_"
        lc_layer = "_lc_layer_tmp_"
        arcpy.management.MakeFeatureLayer(locations_fc, loc_layer)
        arcpy.management.MakeFeatureLayer(landcover_fc, lc_layer)

        desc_loc = arcpy.Describe(locations_fc)
        oid_field = desc_loc.OIDFieldName
        oids = [row[0] for row in arcpy.da.SearchCursor(locations_fc, [oid_field])]
        total = len(oids)
        arcpy.AddMessage(f"Total location features: {total}")

        output_created = False
        global_seq = 1
        seq_field_name = "SeqID"

        try:
            arcpy.management.AddIndex(locations_fc, location_id_field, f"IDX_{location_id_field[:8]}")
        except Exception:
            pass

        batch_number = 0
        temp_to_cleanup = []
        try:
            for start in range(0, total, batch_size):
                batch_number += 1
                end = min(start + batch_size, total)
                batch_oids = oids[start:end]
                arcpy.AddMessage(f"Processing batch {batch_number}: features {start+1}-{end} of {total}")

                clauses = []
                for i in range(0, len(batch_oids), 900):
                    subset = batch_oids[i:i+900]
                    clauses.append(f"{oid_field} IN ({','.join(map(str, subset))})")
                where_clause = " OR ".join(clauses)

                arcpy.management.MakeFeatureLayer(locations_fc, loc_layer, where_clause)
                arcpy.management.SelectLayerByLocation(lc_layer, "INTERSECT", loc_layer, selection_type="NEW_SELECTION")
                landcover_subset = f"in_memory/lc_sub_{batch_number}"
                arcpy.management.CopyFeatures(lc_layer, landcover_subset)
                temp_to_cleanup.append(landcover_subset)

                if int(arcpy.management.GetCount(landcover_subset)[0]) == 0:
                    arcpy.AddMessage("No intersecting landcover features for this batch; skipping.")
                    continue

                intersect_out = f"in_memory/intersect_{batch_number}"
                arcpy.analysis.PairwiseIntersect([loc_layer, landcover_subset], intersect_out)
                temp_to_cleanup.append(intersect_out)

                if seq_field_name not in [f.name for f in arcpy.ListFields(intersect_out)]:
                    arcpy.management.AddField(intersect_out, seq_field_name, "LONG")
                with arcpy.da.UpdateCursor(intersect_out, [seq_field_name]) as cur:
                    for row in cur:
                        row[0] = global_seq
                        cur.updateRow(row)
                        global_seq += 1

                if not output_created:
                    arcpy.management.CopyFeatures(intersect_out, output_fc)
                    output_created = True
                else:
                    arcpy.management.Append(intersect_out, output_fc, "NO_TEST")

                arcpy.management.SelectLayerByAttribute(lc_layer, "CLEAR_SELECTION")

            arcpy.AddMessage("All batches processed.")
        finally:
            if not keep_intermediates:
                for ds in temp_to_cleanup:
                    try:
                        if arcpy.Exists(ds):
                            arcpy.management.Delete(ds)
                    except Exception as e:
                        arcpy.AddMessage(f"Warning: could not delete {ds}: {e}")
                for lyr in [loc_layer, lc_layer]:
                    try:
                        if arcpy.Exists(lyr):
                            arcpy.management.Delete(lyr)
                    except Exception:
                        pass
            arcpy.AddMessage("SpatialJoinDivideTool completed (optimized mode).")

  


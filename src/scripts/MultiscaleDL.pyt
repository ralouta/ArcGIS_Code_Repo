"""This Python script defines a custom ArcGIS Pro toolbox named MultiScaleDL for multi-scale deep learning. 
The toolbox contains a single tool, also named MultiScaleDL.

The MultiScaleDL tool is designed to perform object detection on geospatial raster data using a deep learning model. 
The tool takes several parameters, including an input raster, a list of cell sizes, a deep learning model definition file, 
an output geodatabase, an output feature class name, a batch size, a threshold, a processor type, a GPU ID, and a 
processing extent.

The execute method of the MultiScaleDL tool is where the main functionality resides. It first sets up the environment, 
retrieves the parameters, and prepares for multiple runs of the "Detect Objects Using Deep Learning" function with 
different cell sizes.

For each cell size, it sets the environment, runs the "Detect Objects Using Deep Learning" function, and stores the output. 
The "Detect Objects Using Deep Learning" function is part of the arcpy.ia module and is used to detect objects in the 
input raster based on the provided deep learning model.

The model tool will then perform some high-level QA/QC over the output data then regularize by a pre-set 
tolerance for a list of building areas. The model will then intersect all the output layers to generate 
one final buildings feature class"""

import arcpy
import torch
import os


class Toolbox(object):
    def __init__(self):
        """Define the toolbox (the name of the toolbox is the name of the
        .pyt file)."""
        self.label = "MultiScaleDL"
        self.alias = "Multi Scale Deep Learning"

        # List of tool classes associated with this toolbox
        self.tools = [MultiScaleDL]


class MultiScaleDL(object):
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "MultiScaleDL"
        self.description = "Multi Scale Deep Learning"
        self.canRunInBackground = True

    def getParameterInfo(self):
        """Define parameter definitions"""
        # Define parameters for the tool
        params = [arcpy.Parameter(displayName="Input Raster",
                                name="in_raster",
                                datatype="GPRasterLayer",
                                parameterType="Required",
                                direction="Input"),
                arcpy.Parameter(displayName="Cell Sizes",
                                name="cell_sizes",
                                datatype="GPString",
                                parameterType="Required",
                                direction="Input"),
                arcpy.Parameter(displayName="Model Definition",
                                name="in_model_definition",
                                datatype="DEFile",
                                parameterType="Required",
                                direction="Input"),
                arcpy.Parameter(displayName="Output Geodatabase",
                                name="out_gdb",
                                datatype="DEWorkspace",
                                parameterType="Required",
                                direction="Input"),
                arcpy.Parameter(displayName="Output Feature Class Name",
                                name="out_fc_name",
                                datatype="GPString",
                                parameterType="Required",
                                direction="Input"),
                arcpy.Parameter(displayName="Batch Size",
                                name="batch_size",
                                datatype="GPLong",
                                parameterType="Required",
                                direction="Input"),
                arcpy.Parameter(displayName="Threshold",
                                name="threshold",
                                datatype="GPDouble",
                                parameterType="Required",
                                direction="Input"),
                arcpy.Parameter(displayName="Processor Type",
                                name="processor_type",
                                datatype="GPString",
                                parameterType="Required",
                                direction="Input"),
                arcpy.Parameter(displayName="GPU ID",
                                name="gpu_id",
                                datatype="GPLong",
                                parameterType="Optional",
                                direction="Input"),
                arcpy.Parameter(displayName="Processing Extent",
                                name="processing_extent",
                                datatype="GPExtent",
                                parameterType="Optional",
                                direction="Input")]

        # Set a filter to only accept .dlpk files for the "Model Definition" parameter
        params[2].filter.list = ['dlpk']

        # Set the default value for the "Output Geodatabase" parameter to the ArcGIS Pro default geodatabase
        params[3].value = arcpy.env.workspace

        # Set a filter to only accept "CPU" or "GPU" for the "Processor Type" parameter
        params[7].filter.type = "ValueList"
        params[7].filter.list = ["CPU", "GPU"]

        # Set the default value for processor type to GPU and the "GPU ID" parameter to 0
        params[7].value = "GPU"
        params[8].value = 0

        return params
    def isLicensed(self):
        """Set whether tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal
        validation is performed.  This method is called whenever a parameter
        has been changed."""
        if parameters[0].altered:
            cell_sizes = parameters[0].valueAsText.split(',')
            for cell_size in cell_sizes:
                if not cell_size.isdigit():
                    parameters[0].setErrorMessage("Cell Sizes must be a comma-separated list of numbers.")
        return

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter.  This method is called after internal validation."""
        return
    

    def execute(self, parameters, messages):
        """The source code of the tool."""
        arcpy.AddMessage("Starting execution")
        
        # Set overwrite output to True
        arcpy.env.overwriteOutput = True

        
        
        in_raster = parameters[0].valueAsText
        cell_sizes = parameters[1].valueAsText
        in_model_definition = parameters[2].valueAsText
        out_gdb = parameters[3].valueAsText
        out_fc_name = parameters[4].valueAsText
        batch_size = parameters[5].valueAsText
        threshold = parameters[6].valueAsText
        processor_type = parameters[7].valueAsText
        gpu_id = parameters[8].valueAsText
        processing_extent = parameters[9].valueAsText

        cell_sizes = cell_sizes.split(',')
        
        # Set the GPU ID
        arcpy.env.gpuId = gpu_id

        # Get the spatial reference of the input raster
        spatial_ref = arcpy.Describe(in_raster).spatialReference

        # Set the output coordinate system to be the same as the input raster
        arcpy.env.outputCoordinateSystem = spatial_ref

        # Get the number of times "Detect Objects Using Deep Learning" will run
        num_runs = len(cell_sizes)

        # Report the number of runs
        arcpy.AddMessage(f"'Detect Objects Using Deep Learning' will run {num_runs} times.")

        # Set up the progress bar
        arcpy.SetProgressor("step", "Running 'Detect Objects Using Deep Learning'...", 0, num_runs, 1)

        # List to store building outputs. Will be used to process final buildings layer
        buildings_outputs = []

        for cell_size in cell_sizes:
            arcpy.AddMessage(f"Processing cell size: {cell_size}")
            with arcpy.EnvManager(cellSize=float(cell_size), scratchWorkspace=r"", processorType=processor_type, extent=processing_extent):
                arcpy.AddMessage("Detecting objects using deep learning...")
                out_fc = os.path.join(out_gdb, f"{out_fc_name}_{int(float(cell_size)*100)}_raw")
                arcpy.ia.DetectObjectsUsingDeepLearning(
                    in_raster=in_raster,
                    out_detected_objects=out_fc,
                    in_model_definition=in_model_definition,
                    arguments=f"padding 128;batch_size {batch_size};threshold {threshold};return_bboxes False;test_time_augmentation False;merge_policy mean;tile_size 512",
                    run_nms="NO_NMS",
                    confidence_score_field="Confidence",
                    class_value_field="Class",
                    max_overlap_ratio=0,
                    processing_mode="PROCESS_AS_MOSAICKED_IMAGE"
                )

                arcpy.AddMessage("Objects detected.")

                # Add the output to the map
                arcpy.addOutputsToMap = True

            # Clear the CUDA cache
            arcpy.AddMessage("Clearing CUDA cache...")
            torch.cuda.empty_cache()
            arcpy.AddMessage("CUDA cache cleared.")

            # Repair geometry
            arcpy.AddMessage("Repairing geometry...")
            arcpy.RepairGeometry_management(out_fc)
            arcpy.AddMessage("Geometry repaired.")

            # Delete rows with area > 4500
            arcpy.AddMessage("Deleting rows with area > 4500...")
            with arcpy.da.UpdateCursor(out_fc, "SHAPE@AREA") as cursor:
                for row in cursor:
                    if row[0] > 4500:
                        cursor.deleteRow()
            del cursor
            arcpy.AddMessage("Rows deleted.")

            # Pairwise Buffer
            arcpy.AddMessage("Running Pairwise Buffer...")
            pairwise_buffer_output = arcpy.env.workspace + "\\temp_buffer_negative_30cm"          
            arcpy.analysis.PairwiseBuffer(in_features=out_fc, out_feature_class=pairwise_buffer_output, buffer_distance_or_field="-30 Centimeters")
            arcpy.AddMessage("Pairwise Buffer completed.")

            # Pairwise Dissolve
            arcpy.AddMessage("Running Pairwise Dissolve...")
            pairwise_dissoolve_output_1 = arcpy.env.workspace + "\\temp_dissolve_1"
            arcpy.analysis.PairwiseDissolve(in_features=pairwise_buffer_output, out_feature_class=pairwise_dissoolve_output_1, multi_part="SINGLE_PART")
            arcpy.AddMessage("Pairwise Dissolve completed.")

            # Spatial Join
            arcpy.AddMessage("Running Spatial Join...")
            spatial_join_output = arcpy.env.workspace + "\\temp_spatial_join"
            arcpy.analysis.SpatialJoin(target_features=pairwise_dissoolve_output_1, join_features=pairwise_buffer_output, out_feature_class=spatial_join_output, join_operation="JOIN_ONE_TO_MANY", join_type="KEEP_ALL")
            arcpy.AddMessage("Spatial Join completed.")

            # Pairwise Dissolve - Mean Confidence
            arcpy.AddMessage("Running Pairwise Dissolve - Mean Confidence...")
            pairwise_dissolve_output_2 = arcpy.env.workspace + "\\temp_dissolved_2"
            arcpy.analysis.PairwiseDissolve(in_features=spatial_join_output, out_feature_class=pairwise_dissolve_output_2, dissolve_field=["TARGET_FID"], statistics_fields=[["Confidence", "MEAN"]], multi_part="SINGLE_PART")
            arcpy.AddMessage("Pairwise Dissolve - Mean Confidence completed.")

            # Select Layer By Attribute 6 -1000
            arcpy.AddMessage("Running building classification by area...")

            # Define the output paths
            output_path_1 = arcpy.env.workspace + "\\temp_select_layer_1"
            output_path_2 = arcpy.env.workspace + "\\temp_select_layer_2"
            output_path_3 = arcpy.env.workspace + "\\temp_select_layer_3"
            output_path_4 = arcpy.env.workspace + "\\temp_select_layer_4"
            output_path_5 = arcpy.env.workspace + "\\temp_select_layer_5"

            # Create new feature classes for the output
            arcpy.management.CreateFeatureclass(arcpy.env.workspace, "temp_select_layer_1", template=pairwise_dissolve_output_2)
            arcpy.management.CreateFeatureclass(arcpy.env.workspace, "temp_select_layer_2", template=pairwise_dissolve_output_2)
            arcpy.management.CreateFeatureclass(arcpy.env.workspace, "temp_select_layer_3", template=pairwise_dissolve_output_2)
            arcpy.management.CreateFeatureclass(arcpy.env.workspace, "temp_select_layer_4", template=pairwise_dissolve_output_2)
            arcpy.management.CreateFeatureclass(arcpy.env.workspace, "temp_select_layer_5", template=pairwise_dissolve_output_2)

            # Get a list of field names from the input feature class
            field_names = [field.name for field in arcpy.ListFields(pairwise_dissolve_output_2)]

            # Add 'SHAPE@JSON' to the list of field names
            field_names.append('SHAPE@JSON')

            # Create lists to store the rows
            rows_1 = []
            rows_2 = []
            rows_3 = []
            rows_4 = []
            rows_5 = []

            # Open a search cursor for the input feature class
            with arcpy.da.SearchCursor(pairwise_dissolve_output_2, field_names) as cursor:
                for row in cursor:
                    # Get the value of the Shape_Area field
                    shape_area = row[cursor.fields.index("Shape_Area")]
                    # Check the value and add the row to the appropriate list
                    if 6 < shape_area <= 50:
                        rows_1.append(row)
                    elif 50 < shape_area <= 200:
                        rows_2.append(row)
                    elif 200 < shape_area <= 500:
                        rows_3.append(row)
                    elif 500 < shape_area <= 1000:
                        rows_4.append(row)
                    elif 1000 <= shape_area < 4500:
                        rows_5.append(row)

            # Start an edit session
            editor = arcpy.da.Editor(arcpy.env.workspace)
            editor.startEditing(False, True)
            editor.startOperation()

            # Open insert cursors for the output feature classes and insert the rows
            cursor_1 = arcpy.da.InsertCursor(output_path_1, field_names)
            for row in rows_1:
                cursor_1.insertRow(row)

            cursor_2 = arcpy.da.InsertCursor(output_path_2, field_names)
            for row in rows_2:
                cursor_2.insertRow(row)

            cursor_3 = arcpy.da.InsertCursor(output_path_3, field_names)
            for row in rows_3:
                cursor_3.insertRow(row)

            cursor_4 = arcpy.da.InsertCursor(output_path_4, field_names)
            for row in rows_4:
                cursor_4.insertRow(row)

            cursor_5 = arcpy.da.InsertCursor(output_path_5, field_names)
            for row in rows_5:
                cursor_5.insertRow(row)

            # Stop the edit operation and stop the editing session
            editor.stopOperation()
            editor.stopEditing(True)

            # Define the tolerances
            tolerances = [0.5, 1, 1.5, 2.5, 5]

            # Define the output paths
            output_paths = [output_path_1, output_path_2, output_path_3, output_path_4, output_path_5]
            
            # Run the RegularizeBuildingFootprint function for each tolerance
            for tolerance, output_path in zip(tolerances, output_paths):
                arcpy.AddMessage(f"Running Regularizing Building Footprints with tolerance {tolerance}...")
                tolerance_cm = int(tolerance * 100)
                buildings_output = f"{arcpy.env.workspace}\\Buildings_{tolerance_cm}cm"
                arcpy.AddMessage(f"Regularizing Building Footprints with tolerance {tolerance}...")
                arcpy.ddd.RegularizeBuildingFootprint(in_features=output_path, out_feature_class=buildings_output, method="RIGHT_ANGLES", tolerance=tolerance)
                output_paths.append(buildings_output)
                arcpy.AddMessage(f"Regularizing Building Footprints with tolerance {tolerance} completed.")

            # Merge
            arcpy.AddMessage("Running Merge...")
            merge_output = f"{arcpy.env.workspace}\\{out_fc_name}_{int(float(cell_size)*100)}"
            arcpy.management.Merge(inputs=[f"{arcpy.env.workspace }\\Buildings_{int(tolerance * 100)}cm" for tolerance in tolerances], output=merge_output)
            
            buildings_outputs.append(merge_output)

            arcpy.AddMessage("Merge completed.")

            # Delete temporary outputs
            arcpy.AddMessage("Deleting temporary outputs...")
            for output_path in output_paths:
                arcpy.Delete_management(output_path)
            arcpy.Delete_management(pairwise_buffer_output)
            arcpy.Delete_management(spatial_join_output)
            arcpy.Delete_management(pairwise_buffer_output)
            arcpy.Delete_management(spatial_join_output)
            arcpy.Delete_management(pairwise_dissoolve_output_1)
            arcpy.Delete_management(pairwise_dissolve_output_2)
            arcpy.AddMessage("Temporary outputs deleted.")

             # Clear the CUDA cache
            arcpy.AddMessage("Clearing CUDA cache...")
            torch.cuda.empty_cache()
            arcpy.AddMessage("CUDA cache cleared.")

            # Update the progress bar
            arcpy.SetProgressorPosition()
        
        # Get a list of field names from the first input feature class
        field_names = [field.name for field in arcpy.ListFields(buildings_outputs[0])]
        field_names.append('SHAPE@JSON')

        # Copy the 40cm output cell size as the base final layer
        final_layer = f"{arcpy.env.workspace }\\{out_fc_name}"
        arcpy.AddMessage("Creating final layer...")

        # Choose the building output that has the closest cell size to 40cm
        closest_building_output = min(buildings_outputs, key=lambda x: abs((float(x.split('_')[-1])/100) - 0.4))

        arcpy.CopyFeatures_management(closest_building_output, final_layer)
        arcpy.AddMessage("Final layer created.")

        # Sort the buildings_outputs based on their cell sizes
        buildings_outputs.sort(key=lambda x: abs(float(x.split('_')[-1]) - 0.4))

        for buildings_output in buildings_outputs:
            if buildings_output != closest_building_output:
                source_fc_name = buildings_output.split("\\")[-1]
                arcpy.AddMessage(f"Processing {source_fc_name}...")

                # Perform pairwise intersection between the base layer and the current output
                intersect_output = f"{arcpy.env.workspace }\\intersect_output"
                arcpy.analysis.PairwiseIntersect(
                    in_features=[final_layer, buildings_output],
                    out_feature_class= intersect_output,
                    join_attributes="ALL",
                    cluster_tolerance=None,
                    output_type="INPUT")
                arcpy.AddMessage(f"Performed pairwise intersection with {source_fc_name}.")

                # Check if the feature intersects with any feature in the intersect output
                intersect_search_cursor =  arcpy.da.SearchCursor(intersect_output, f'FID_{source_fc_name}')

                intersect_objectids = []
                for row in intersect_search_cursor:
                    intersect_objectids.append(row[0])

                del intersect_search_cursor

                # Open a search cursor for the current output
                source_features_cursor = arcpy.da.SearchCursor(buildings_output, field_names)

                features_to_insert = []

                if intersect_objectids:
                    for row in source_features_cursor:
                        # Check if the value of field_names[0] is not in intersect_objectids
                        if row[0] not in intersect_objectids:
                            # If it is not in intersect_objectids, print it (or do whatever you need with it)
                            features_to_insert.append(row)
                    del source_features_cursor

                if features_to_insert:
                    arcpy.AddMessage(f"Inserting features from {source_fc_name} into final layer...")

                    # Start an edit session
                    editor = arcpy.da.Editor(arcpy.env.workspace)
                    editor.startEditing(False, True)
                    editor.startOperation()

                    # Open an insert cursor for the base final layer
                    final_layer_insert_cursor = arcpy.da.InsertCursor(final_layer, field_names)
                    for feature in features_to_insert:
                        # Insert the feature into the base final layer
                        final_layer_insert_cursor.insertRow(feature)
                    del final_layer_insert_cursor

                    # Stop the edit operation and stop the editing session
                    editor.stopOperation()
                    editor.stopEditing(True)

                    arcpy.AddMessage(f"Inserted features from {source_fc_name} into final layer.")

                # Delete the intersect output to free up memory
                arcpy.Delete_management(intersect_output)
                arcpy.AddMessage(f"Deleted intersect output for {source_fc_name}.")

        arcpy.AddMessage("Processing completed.")
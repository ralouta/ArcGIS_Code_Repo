"""
MultiResolutionDL.pyt

This Python toolbox contains a set of tools for performing multi-resolution deep learning tasks. 

The primary tool in this toolbox, MultiScaleDL, allows users to apply deep learning models to raster data at multiple scales. 

This can be particularly useful for tasks such as feature extraction, where the size of the features of interest can vary widely.

The tool accepts a variety of input parameters, including the input raster, cell sizes, deep learning workflow, model definition, and output geodatabase, among others. 
It also provides options for regularizing or generalizing the output feature. 

The toolbox is designed to work with ArcGIS Pro and uses arcpy, the ArcGIS Python module, for many of its operations.
"""

import arcpy
from arcpy.sa import *
import arcpy.management

import requests

import re

import torch
import os

import statistics

import math

import json

import subprocess


def bounding_box_to_circle(input_feature_class, output_buffer_feature_class):
        # Step 1: Add a new field "Radius" to the input feature class
        arcpy.management.AddField(input_feature_class, "Radius", "DOUBLE")

        # Use an UpdateCursor to calculate the radius for each feature
        with arcpy.da.UpdateCursor(input_feature_class, ["SHAPE@AREA", "Radius"]) as cursor:
            for row in cursor:
                # Calculate the radius from the area
                radius = math.sqrt(row[0] / math.pi)
                # Update the Rdius field
                row[1] = radius*0.85
                cursor.updateRow(row)
        # Step 3: Use FeatureToPoint to convert the updated input feature class to a temporary point feature class
        temp_point_feature_class = "temp_point_feature"
        arcpy.management.FeatureToPoint(input_feature_class, temp_point_feature_class, "INSIDE")

        # Step 4: Use Buffer to create the final output buffer based on the "Radius" field
        arcpy.analysis.Buffer(temp_point_feature_class, output_buffer_feature_class, "Radius")

        # Optional: Delete the temporary point feature class
        arcpy.management.Delete(temp_point_feature_class)

def return_extents(out_gdb, in_raster, processing_extent, cell_size, pixels_extent):
    if "NaN" in processing_extent:
        processing_extent = processing_extent.split("NaN")[0]
    # Calculate the number of pixels in the extent
    extent_width = float(processing_extent.split(' ')[2]) - float(processing_extent.split(' ')[0])
    extent_height = float(processing_extent.split(' ')[3]) - float(processing_extent.split(' ')[1])
    
    # Calculate the number of sub-extents needed
    num_pixels = (extent_width / cell_size) * (extent_height / cell_size)
    num_sub_extents = math.ceil(num_pixels / pixels_extent)
    
    # Calculate the width and height of each sub-extent
    sub_extent_width = extent_width / num_sub_extents
    sub_extent_height = extent_height / num_sub_extents
    
    # Create a new feature class to store the extents
    extent_fc = arcpy.management.CreateFeatureclass(out_path=out_gdb, out_name="ExtentFC",
                                                     geometry_type="POLYGON", spatial_reference=in_raster)

    # Create an insert cursor
    cursor = arcpy.da.InsertCursor(extent_fc, ["SHAPE@"])

    num_sub_extents_x = math.ceil(extent_width / sub_extent_width)
    num_sub_extents_y = math.ceil(extent_height / sub_extent_height)

    for i in range(num_sub_extents_x):
        for j in range(num_sub_extents_y):
            # Calculate the sub-extent
            sub_extent = arcpy.Extent(
                float(processing_extent.split(' ')[0]) + i * sub_extent_width,
                float(processing_extent.split(' ')[1]) + j * sub_extent_height,
                float(processing_extent.split(' ')[0]) + (i + 1) * sub_extent_width if i+1 < num_sub_extents_x else float(processing_extent.split(' ')[2]),
                float(processing_extent.split(' ')[1]) + (j + 1) * sub_extent_height if j+1 < num_sub_extents_y else float(processing_extent.split(' ')[3])
            )


            # Create a polygon from the extent
            array = arcpy.Array([arcpy.Point(sub_extent.XMin, sub_extent.YMin),
                                arcpy.Point(sub_extent.XMin, sub_extent.YMax),
                                arcpy.Point(sub_extent.XMax, sub_extent.YMax),
                                arcpy.Point(sub_extent.XMax, sub_extent.YMin)])
            polygon = arcpy.Polygon(array)

            # Insert the polygon into the feature class
            cursor.insertRow([polygon])

    # Clean up the cursor
    del cursor

    
    arcpy.env.workspace = out_gdb
    with arcpy.EnvManager(cellSize=100, extent=processing_extent):
        # Check if in_raster is a URL
        if in_raster.startswith('http'):
            # Step 1: Create an image server layer
            image_server_layer = arcpy.MakeImageServerLayer_management(in_raster, "RasterLayer")
        else:
            # Step 1: Create a raster layer
            raster_layer = arcpy.MakeRasterLayer_management(in_raster, "RasterLayer")


        # Step 2: Multiply the raster by 0 to create a constant value raster
        # Ensure Spatial Analyst extension is checked out
        arcpy.CheckOutExtension("Spatial")

        # Create a Raster object from the image server layer
        raster = arcpy.Raster("RasterLayer")

        # Multiply the raster by 0
        zero_raster = raster * 0

        # Convert the raster to integer type
        int_raster = Int(zero_raster)

        # Save the result
        int_raster.save("ZeroRaster")


        # Step 3: Convert the result to polygon
        polygon = arcpy.RasterToPolygon_conversion("ZeroRaster", "ZeroPolygon", "NO_SIMPLIFY")

    # Step 4: Spatial join the output polygon with the polygon created in the previous step
    joined_polygon = arcpy.SpatialJoin_analysis(extent_fc, polygon, os.path.join(out_gdb, "JoinedPolygon"))

    # Open the joined polygon feature class with an UpdateCursor
    with arcpy.da.UpdateCursor("JoinedPolygon", ["Join_Count"]) as cursor:
        for row in cursor:
            # If the Join_Count field is 0, delete the row
            if row[0] == 0:
                cursor.deleteRow()
    # Create an empty list to store the extents
    extents = []

    # Open the joined polygon feature class with a SearchCursor
    with arcpy.da.SearchCursor("JoinedPolygon", ["SHAPE@"]) as cursor:
        for row in cursor:
            # Get the extent of the feature
            extent = row[0].extent
            # Add the extent to the list
            extents.append(extent)

    arcpy.management.Delete("ZeroRaster")
    arcpy.management.Delete("ZeroPolygon")
    #arcpy.management.Delete(os.path.join(out_gdb, "JoinedPolygon"))
    arcpy.management.Delete(extent_fc)
   
    arcpy.AddMessage(f"Number of sub-extents: {len(extents)}")
   
    return extents

class Toolbox(object):
    def __init__(self):
        """Define the toolbox (the name of the toolbox is the name of the
        .pyt file)."""
        self.label = "MultiResolutionDL"
        self.alias = "Multi Resolution Deep Learning"

        # List of tool classes associated with this toolbox
        self.tools = [MultiScaleDL]

        
class MultiScaleDL(object):
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "Multi Resolution Deep Learning"
        self.description = "Multi Resolution Deep Learning"
        self.canRunInBackground = True

    def getParameterInfo(self):
        """Define parameter definitions"""
        # Define parameters for the tool
        params = [arcpy.Parameter(displayName="Input Raster",
                                name="in_raster",
                                datatype=["DEMapServer", "GPRasterDataLayer", "DEImageServer", "DEMosaicDataset",
                                           "DERasterDataset", "GPRasterLayer"],
                                parameterType="Required",
                                direction="Input"),
                arcpy.Parameter(displayName="Cell Sizes",
                                name="cell_sizes",
                                datatype="GPString",
                                parameterType="Required",
                                direction="Input"),
                arcpy.Parameter(displayName="Use Average Cell Size",
                                name="use_avg_cell_size",
                                datatype="GPBoolean",
                                parameterType="Optional",
                                direction="Input"),
                arcpy.Parameter(displayName="Specified Cell Size",
                                name="specified_cell_size",
                                datatype="GPDouble",
                                parameterType="Required",
                                direction="Input"),
                arcpy.Parameter(displayName="Deep Learning Workflow",
                                name="dl_workflow",
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
                arcpy.Parameter(displayName="Text Prompt",
                                name="text_prompt",
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
                                parameterType="Optional",
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
                                direction="Input"),
                arcpy.Parameter(displayName="Processing Mask",
                                name="processing_mask",
                                datatype="DEFeatureClass",
                                parameterType="Optional",
                                direction="Input"),
                arcpy.Parameter(displayName="Minimum Area",
                                name="min_area",
                                datatype="GPLong",
                                parameterType="Optional",
                                direction="Input"),
                arcpy.Parameter(displayName="Maximum Area", 
                                name="max_area",
                                datatype="GPLong",
                                parameterType="Optional",
                                direction="Input"),
                arcpy.Parameter(displayName="Regularize or Generalize the output feature",
                                name="regularize_generalize",
                                datatype="GPString",
                                parameterType="Required",
                                direction="Input")]
                

        # Set the parameter's filter to a ValueList to create a dropdown menu
        params[4].filter.type = 'ValueList'
        params[4].filter.list = ['General Feature Extraction', 'Text SAM Feature Extraction']

        # Set a filter to only accept .dlpk files for the "Model Definition" parameter
        params[5].filter.list = ['dlpk']

        # Set the default value for the "Output Geodatabase" parameter to the ArcGIS Pro default geodatabase
        params[6].value = arcpy.env.workspace

        #Set the defailt text prompt to ""
        params[8].value = " "

        #set the value of the "Threshold" parameter to 0.65
        params[10].value = 0.65
        
        # Set a filter to only accept "CPU" or "GPU" for the "Processor Type" parameter
        params[11].filter.type = "ValueList"
        params[11].filter.list = ["CPU", "GPU"]

        # Set the default value for processor type to GPU and the "GPU ID" parameter to 0
        params[11].value = "GPU"
        params[12].value = 0
        params[15].value = 4.0
        params[16].value = 4500.0

        # Set the filter for the "Regularize or Generalize the output feature" parameter
        params[17].filter.type = "ValueList"
        params[17].filter.list = ["Regularize Right Angle", "Regularize Circle", "Generalize"]

        return params
    def isLicensed(self):
        """Set whether tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal
        validation is performed.  This method is called whenever a parameter
        has been changed."""
        if parameters[1].valueAsText:
            # Regular expression for decimal values separated by commas
            pattern = r'^(\d+(\.\d+)?,)*\d+(\.\d+)?$'
            if not re.match(pattern, parameters[1].valueAsText):
                parameters[1].setErrorMessage('Invalid input format. Please enter decimal values separated by commas.')

        # Enable or disable text prompt or threshold based on the selected deep learning workflow.        
        parameters[8].enabled = False
        parameters[10].enabled = False

        if parameters[4].valueAsText == 'Text SAM Feature Extraction':
            parameters[8].enabled = True
            parameters[10].enabled = False
        elif parameters[4].valueAsText == 'General Feature Extraction':
            parameters[8].enabled = False
            parameters[10].enabled = True

        if parameters[2].value:
            parameters[3].enabled = False
        else:
            parameters[3].enabled = True
        return

    
    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter.  This method is called after internal validation."""
        if parameters[1].hasBeenValidated and parameters[1].valueAsText and not re.match(r'^(\d+(\.\d+)?,)*\d+(\.\d+)?$', parameters[1].valueAsText):
            parameters[1].setErrorMessage('Invalid input format. Please enter decimal values separated by commas.')
        return
    
    def execute(self, parameters, messages):
        """The source code of the tool."""
        arcpy.AddMessage("Starting execution")
        
        # Set overwrite output to True
        arcpy.env.overwriteOutput = True
        
        
        in_raster = parameters[0].valueAsText
        cell_sizes = parameters[1].valueAsText
        use_avg_cell_size = parameters[2].value
        specified_cell_size = parameters[3].value
        dl_workflow = parameters[4].valueAsText
        in_model_definition = parameters[5].valueAsText
        out_gdb = parameters[6].valueAsText
        out_fc_name = parameters[7].valueAsText
        text_prompt = parameters[8].valueAsText
        batch_size = parameters[9].valueAsText
        threshold = parameters[10].value
        processor_type = parameters[11].valueAsText
        gpu_id = parameters[12].valueAsText
        processing_extent = parameters[13].valueAsText
        processing_mask = parameters[14].valueAsText
        min_area = parameters[15].value
        max_area = parameters[16].value
        regularize_generalize = parameters[17].valueAsText

        # Define the tolerances
        tolerances = {"Regularize Right Angle":[[0.5, 1, 1.5, 2.5, 3.5, 5],[(1, 50), (50, 200), (200, 500), (500, 1000), (1000, 4500), (4500, float('inf'))]],
                    "Regularize Circle":[[1],[(min_area, max_area)]],
                    "Generalize":[[0.5, 1, 1.5, 2.5, 3.5, 5],[(1, 50), (50, 200), (200, 500), (500, 1000), (1000, 4500), (4500, float('inf'))]]}

        cell_sizes = cell_sizes.split(',')
        
        # Convert strings to floats
        cell_sizes = [float(size) for size in cell_sizes]

        
        # Calculate the mean
        if use_avg_cell_size:
            chozen_cell_size = statistics.mean(cell_sizes)
        else:
            chozen_cell_size = specified_cell_size

        # Set the GPU ID
        arcpy.env.gpuId = gpu_id

        # Clear the CUDA cache
        arcpy.AddMessage("Clearing CUDA cache...")
        torch.cuda.empty_cache()
        arcpy.AddMessage("CUDA cache cleared.")

        
        # Define the command as a string
        command = "start cmd /k nvidia-smi -l 5"

        # Use subprocess to run the command
        process = subprocess.Popen(command, shell=True)

        # Check if in_raster is a URL
        if in_raster.startswith('http'):
            # Get a token from the active portal
            token = arcpy.GetSigninToken()['token']

            rest_url = f'{in_raster}?token={token}&f=pjson'
            # Send a GET request to the REST URL
            response = requests.get(rest_url)
            # Parse the JSON response
            json_response = response.json()

            # Get the spatial reference
            spatial_ref = json_response['spatialReference']
            wkid = spatial_ref['wkid']
            # Create a Spatial Reference object
            spatial_ref_obj = arcpy.SpatialReference(wkid)

            arcpy.AddMessage(f"The spatial reference of the input raster is {wkid}.")
                
        else:
            # Get the spatial reference of the input raster
            desc = arcpy.Describe(in_raster)
            spatial_ref_obj = desc.spatialReference
        # Set the output coordinate system to be the same as the input raster
        arcpy.env.outputCoordinateSystem = spatial_ref_obj

        # Get the number of times "Detect Objects Using Deep Learning" will run
        num_runs = len(cell_sizes)

        # Report the number of runs
        arcpy.AddMessage(f"'Detect Objects Using Deep Learning' will run {num_runs} times.")

        # Set up the progress bar
        arcpy.SetProgressor("step", "Running 'Detect Objects Using Deep Learning'...", 0, num_runs, 1)

        # List to store building outputs. Will be used to process final buildings layer
        features_outputs = []

        for cell_size in cell_sizes:
            
            merge_output = f"{arcpy.env.workspace}\\{out_fc_name}_{int(float(cell_size)*100)}"
            arcpy.AddMessage(f"Processing cell size: {cell_size}")

            out_fc = os.path.join(out_gdb, f"{out_fc_name}_{int(float(cell_size)*100)}_raw")
            
            # Set pixels_extent based on cell_size
            if cell_size <= 0.25:
                pixels_extent = 150000000
            elif 0.25 < cell_size <= 0.35:
                pixels_extent = 200000000
            else:
                pixels_extent = 250000000

            # Calculate the number of pixels in the extent
            extent_width = float(processing_extent.split(' ')[2]) - float(processing_extent.split(' ')[0])
            extent_height = float(processing_extent.split(' ')[3]) - float(processing_extent.split(' ')[1])
            num_pixels = (extent_width / cell_size) * (extent_height / cell_size)
            arcpy.AddMessage(f"Number of pixels: {num_pixels}")
            
            if dl_workflow == 'General Feature Extraction':
                arguments = f"padding 128;batch_size {batch_size};threshold {threshold};return_bboxes False;test_time_augmentation False;merge_policy mean;tile_size 512"
            elif dl_workflow == 'Text SAM Feature Extraction':
                arguments = f"text_prompt {text_prompt};padding 128;batch_size {batch_size};box_threshold 0.1;text_threshold 0.05;box_nms_thresh 0.7;tile_size 512"
                            
            if not arcpy.Exists(out_fc):
                # If the number of pixels is more than 100,000, divide the extent
                if num_pixels > pixels_extent:
                    extents = return_extents(out_gdb, in_raster, processing_extent, cell_size, pixels_extent)
                    for i in range(len(extents)):
                        with arcpy.EnvManager(cellSize=cell_size, mask=processing_mask, processorType=processor_type, extent=extents[i]):
                            arcpy.AddMessage(f"Detecting objects using deep learning for sub-extent {i}...")
                            out_fc_subextent = os.path.join(out_gdb, f"{out_fc_name}_{int(float(cell_size)*100)}_{i}_raw")
                            if not arcpy.Exists(out_fc_subextent):
                                for attempt in range(2):
                                    try:
                                        if attempt == 0:                                                
                                            arcpy.ia.DetectObjectsUsingDeepLearning(
                                                in_raster=in_raster,
                                                out_detected_objects=out_fc_subextent,
                                                in_model_definition=in_model_definition,
                                                arguments=arguments,
                                                run_nms="NO_NMS",
                                                confidence_score_field="Confidence",
                                                class_value_field="Class",
                                                max_overlap_ratio=0,
                                                processing_mode="PROCESS_AS_MOSAICKED_IMAGE"
                                            )
                                            torch.cuda.empty_cache()
                                            break # If the operation is successful, break the loop
                                        else:
                                            sub_extents = return_extents(out_gdb, in_raster, str(extents[i]), cell_size, int(pixels_extent/2))
                                            for j in range(len(sub_extents)):
                                                out_fc_subextent_j = os.path.join(out_gdb, f"{out_fc_name}_{int(float(cell_size)*100)}_{i}_{j}_raw")
                                                with arcpy.EnvManager(cellSize=cell_size/2, mask=processing_mask, processorType=processor_type, extent=sub_extents[j]):
                                                    arcpy.AddMessage(f"Detecting objects using deep learning for sub-extent {i} {j}...")
                                                    arcpy.ia.DetectObjectsUsingDeepLearning(
                                                        in_raster=in_raster,
                                                        out_detected_objects=out_fc_subextent_j,
                                                        in_model_definition=in_model_definition,
                                                        arguments=arguments,
                                                        run_nms="NO_NMS",
                                                        confidence_score_field="Confidence",
                                                        class_value_field="Class",
                                                        max_overlap_ratio=0,
                                                        processing_mode="PROCESS_AS_MOSAICKED_IMAGE"
                                                    )
                                                    torch.cuda.empty_cache()
                                    except Exception as e:
                                        if attempt == 0:
                                            arcpy.AddMessage(f"An error occurred: {e} Retrying...")
                                            torch.cuda.empty_cache()
                                            arcpy.Delete_management(out_fc_subextent)
                                        else:
                                            arcpy.Delete_management(out_fc_subextent)
                                            arcpy.AddMessage(f"An error occurred: {e} Skipping...")
                                            break
                                                    
                            # Clear the CUDA cache
                            torch.cuda.empty_cache()

                    out_fcs = [os.path.join(out_gdb, fc) for fc in arcpy.ListFeatureClasses(f"{out_fc_name}_{int(float(cell_size)*100)}_*_raw")]
                    arcpy.management.Merge(out_fcs, f"{out_gdb}\\{out_fc_name}_{int(float(cell_size)*100)}_raw")
                    arcpy.Delete_management(out_fcs)
                else:
                    with arcpy.EnvManager(cellSize=cell_size, scratchWorkspace=r"", mask=processing_mask, processorType=processor_type, extent=processing_extent):
                        arcpy.AddMessage("Detecting objects using deep learning...")                       
                        for attempt in range(2):
                            try:
                                if attempt == 0:                                        
                                    arcpy.ia.DetectObjectsUsingDeepLearning(
                                        in_raster=in_raster,
                                        out_detected_objects=out_fc,
                                        in_model_definition=in_model_definition,
                                        arguments=arguments,
                                        run_nms="NO_NMS",
                                        confidence_score_field="Confidence",
                                        class_value_field="Class",
                                        max_overlap_ratio=0,
                                        processing_mode="PROCESS_AS_MOSAICKED_IMAGE"
                                    )
                                    # Clear the CUDA cache
                                    arcpy.AddMessage("Clearing CUDA cache...")
                                    torch.cuda.empty_cache()
                                    arcpy.AddMessage("CUDA cache cleared.")
                                    break # If the operation is successful, break the loop
                                else:
                                    arcpy.AddMessage("GPU ran out of memory. Dividing the extent and trying again...")

                                    sub_extents = return_extents(out_gdb, in_raster, processing_extent, cell_size, int(pixels_extent/2))
                                    for i in range(len(sub_extents)):
                                        arcpy.AddMessage(f"Detecting objects using deep learning for sub-extent {i}...")
                                        out_fc_subextent = os.path.join(out_gdb, f"{out_fc_name}_{int(float(cell_size)*100)}_{i}_raw")
                                        with arcpy.EnvManager(cellSize=cell_size/2, mask=processing_mask, processorType=processor_type, extent=sub_extents[i]):
                                            arcpy.ia.DetectObjectsUsingDeepLearning(
                                                in_raster=in_raster,
                                                out_detected_objects=out_fc_subextent,
                                                in_model_definition=in_model_definition,
                                                arguments=arguments,
                                                run_nms="NO_NMS",
                                                confidence_score_field="Confidence",
                                                class_value_field="Class",
                                                max_overlap_ratio=0,
                                                processing_mode="PROCESS_AS_MOSAICKED_IMAGE"
                                            )
                                            # Clear the CUDA cache
                                            arcpy.AddMessage("Clearing CUDA cache...")
                                            torch.cuda.empty_cache()
                                            arcpy.AddMessage("CUDA cache cleared.")
                                    out_fcs = [os.path.join(out_gdb, fc) for fc in arcpy.ListFeatureClasses(f"{out_fc_name}_{int(float(cell_size)*100)}_*_raw")]
                                    arcpy.management.Merge(out_fcs, f"{out_gdb}\\{out_fc_name}_{int(float(cell_size)*100)}_raw")
                                    arcpy.Delete_management(out_fcs)
                                    
                            except Exception as e:
                                if attempt == 0:
                                    arcpy.AddMessage(f"An error occurred: {e} Retrying...")
                                    torch.cuda.empty_cache()
                                    arcpy.Delete_management(out_fc_subextent)
                                else:
                                    arcpy.Delete_management(out_fc_subextent)
                                    arcpy.AddMessage(f"An error occurred: {e} Skipping...")
                                    break
                        
            if not arcpy.Exists(merge_output):
                # Repair geometry
                arcpy.AddMessage("Repairing geometry...")
                arcpy.RepairGeometry_management(out_fc)
                arcpy.AddMessage("Geometry repaired.")

                # Delete rows with area > 4500
                arcpy.AddMessage(f"Deleting rows with areas < {min_area} and areas > {max_area}")
                with arcpy.da.UpdateCursor(out_fc, "SHAPE@AREA") as cursor:
                    for row in cursor:
                        if row[0] is None or row[0]< min_area or row[0] > max_area:
                            cursor.deleteRow()
                del cursor
                arcpy.AddMessage("Rows deleted.")

                # Pairwise Buffer
                arcpy.AddMessage("Running Pairwise Buffer...")
                if regularize_generalize == "Regularize Right Angle" or regularize_generalize == "Generalize":
                    buffer_distance = "30"
                else:
                    buffer_distance = "100"
                pairwise_buffer_output = os.path.join(out_gdb, f"{out_fc_name}_{int(float(cell_size)*100)}_pairwise_buffer")         
                arcpy.analysis.PairwiseBuffer(in_features=out_fc, out_feature_class=pairwise_buffer_output, buffer_distance_or_field=f"-{buffer_distance} Centimeters")

                # Pairwise Dissolve
                arcpy.AddMessage("Running Pairwise Dissolve...")
                pairwise_dissoolve_output_1 = os.path.join(out_gdb, f"{out_fc_name}_{int(float(cell_size)*100)}_dissolved")
                arcpy.analysis.PairwiseDissolve(in_features=pairwise_buffer_output, out_feature_class=pairwise_dissoolve_output_1, multi_part="SINGLE_PART")
                arcpy.AddMessage("Pairwise Dissolve completed.")

                # Spatial Join
                arcpy.AddMessage("Running Spatial Join...")
                spatial_join_output = os.path.join(out_gdb, f"{out_fc_name}_{int(float(cell_size)*100)}_spatial_join")
                arcpy.analysis.SpatialJoin(target_features=pairwise_dissoolve_output_1, join_features=pairwise_buffer_output, out_feature_class=spatial_join_output, join_operation="JOIN_ONE_TO_MANY", join_type="KEEP_ALL")
                arcpy.AddMessage("Spatial Join completed.")

                # Pairwise Dissolve - Mean Confidence
                arcpy.AddMessage("Running Pairwise Dissolve - Mean Confidence...")
                pairwise_dissolve_output_2 = os.path.join(out_gdb, f"{out_fc_name}_{int(float(cell_size)*100)}_dissolved_2")
                arcpy.analysis.PairwiseDissolve(in_features=spatial_join_output, out_feature_class=pairwise_dissolve_output_2, dissolve_field=["TARGET_FID"], statistics_fields=[["Confidence", "MEAN"]], multi_part="SINGLE_PART")
                arcpy.AddMessage("Pairwise Dissolve - Mean Confidence completed.")

                # Select Layer By Attribute 6 -1000
                arcpy.AddMessage("Running feature classification by area...")

                # Define the output paths
                output_paths = [f"{os.path.join(out_gdb, out_fc_name)}_{int(float(cell_size)*100)}_{int(tolerance*100)}" for tolerance in tolerances[regularize_generalize][0]]


                # Create new feature classes for the output
                for output_path in output_paths:
                    arcpy.management.CreateFeatureclass(out_gdb, output_path.split("\\")[-1], template=pairwise_dissolve_output_2)
                # Get a list of field names from the input feature class
                field_names = [field.name for field in arcpy.ListFields(pairwise_dissolve_output_2)]

                # Add 'SHAPE@JSON' to the list of field names
                field_names.append('SHAPE@JSON')
                
                # Create a list of empty lists based on the count of tolerances
                rows = [[] for _ in tolerances[regularize_generalize][0]]


                # Open a search cursor for the input feature class
                with arcpy.da.SearchCursor(pairwise_dissolve_output_2, field_names) as cursor:
                    for row in cursor:
                        # Get the value of the Shape_Area field
                        shape_area = row[cursor.fields.index("Shape_Area")]
                        # Check the value and add the row to the appropriate list
                        for i, tolerance in enumerate(tolerances[regularize_generalize][1]):
                            lower, upper = tolerance
                            if lower < shape_area <= upper:
                                rows[i].append(row)
                                break
                del cursor
                
                # Start an edit session
                editor = arcpy.da.Editor(arcpy.env.workspace)
                editor.startEditing(False, True)
                editor.startOperation()

                # Open insert cursors for the output feature classes and insert the rows
                for output_path, rows in zip(output_paths, rows):
                    cursor = arcpy.da.InsertCursor(output_path, field_names)
                    for row in rows:
                        cursor.insertRow(row)
                    del cursor

                # Stop the edit operation and stop the editing session
                editor.stopOperation()
                editor.stopEditing(True)

                regularized_outputs = []

                # Run the RegularizeBuildingFootprint function for each tolerance
                for tolerance, output_path in zip(tolerances[regularize_generalize][0], output_paths):
                    # Set the maximum number of retries
                    max_retries = 5

                    # Initialize the number of attempts
                    attempts = 0
                    if regularize_generalize == "Regularize Right Angle":
                        arcpy.AddMessage(f"Running Regularizing Rectangular Footprints with tolerance {tolerance}...")
                        tolerance_cm = int(tolerance * 100)
                        regularized_output = f"{arcpy.env.workspace}\\rectangle_{tolerance_cm}cm"
                        arcpy.AddMessage(f"Regularizing Rectangular Footprints with tolerance {tolerance}...")
                        
                        while attempts < max_retries:
                            try:
                                # Try to regularize the building footprint
                                with arcpy.EnvManager(processorType=processor_type):
                                    arcpy.ddd.RegularizeBuildingFootprint(in_features=output_path, out_feature_class=regularized_output, method="RIGHT_ANGLES", tolerance=tolerance)
                                    break  # If the operation is successful, break the loop
                            except Exception as e:
                                arcpy.AddMessage(f"An error occurred: {e}/n Cancel the tool and restart ArcGIS Pro.")
                                attempts += 1  # Increase the number of attempts
                                print(f"Retrying ({attempts}/{max_retries})...")
                                time.sleep(5)  # Wait for 5 seconds before retrying

                        regularized_outputs.append(regularized_output)
                        arcpy.AddMessage(f"Regularizing Rectangular Footprints with tolerance {tolerance} completed.")
                        torch.cuda.empty_cache()
                        
                    elif regularize_generalize == "Regularize Circle":
                        arcpy.AddMessage(f"Running Regularizing Circular objects with tolerance {tolerance}...")
                        tolerance_cm = int(tolerance * 100)
                        regularized_output = f"{arcpy.env.workspace}\\circle_{tolerance_cm}cm"
                        bounding_box_to_circle(output_path, regularized_output)
                        regularized_outputs.append(regularized_output)
                        arcpy.AddMessage(f"Regularizing Circular objects with tolerance {tolerance} completed.")
                        torch.cuda.empty_cache()
                    
                    else:
                        arcpy.AddMessage(f"Running Generalizing features with tolerance {tolerance}...")
                        tolerance_cm = int(tolerance * 100)
                        generalized_output = f"{arcpy.env.workspace}\\Buildings_{tolerance_cm}cm"
                        arcpy.AddMessage(f"Generalizing Building Footprints with tolerance {tolerance}...")
                        arcpy.Copy_management(output_path, generalized_output)
                        arcpy.edit.Generalize(in_features=generalized_output, tolerance=tolerance)
                        regularized_outputs.append(generalized_output)
                        arcpy.AddMessage(f"Generalizing features with tolerance {tolerance} completed.")
                        torch.cuda.empty_cache()
                # Delete temporary outputs
                arcpy.AddMessage("Deleting temporary outputs...")
                
                arcpy.Delete_management(pairwise_buffer_output)
                arcpy.Delete_management(spatial_join_output)
                arcpy.Delete_management(pairwise_buffer_output)
                arcpy.Delete_management(spatial_join_output)
                arcpy.Delete_management(pairwise_dissoolve_output_1)
                arcpy.Delete_management(pairwise_dissolve_output_2)
                for output_path in output_paths:
                    arcpy.Delete_management(output_path)
                features_outputs.append(merge_output)
                arcpy.AddMessage("Temporary outputs deleted.")

                # Merge
                arcpy.AddMessage("Running Merge...")
                arcpy.AddMessage(f"Running Merge for {output_paths}...")
                arcpy.management.Merge(inputs=[processed_output_path for processed_output_path in regularized_outputs], output=merge_output)
                for regularized_output in regularized_outputs:
                    arcpy.Delete_management(regularized_output)
                arcpy.AddMessage("Merge completed.")
        

            # Clear the CUDA cache
        arcpy.AddMessage("Clearing CUDA cache...")
        torch.cuda.empty_cache()
        arcpy.AddMessage("CUDA cache cleared.")

        # Update the progress bar
        arcpy.SetProgressorPosition()
        
        arcpy.management.Merge(features_outputs, f"{out_fc_name}_Merged", "", "ADD_SOURCE_INFO")
        arcpy.management.Dissolve(f"{out_fc_name}_Merged", f"{out_fc_name}_Dissolved", "", "", "SINGLE_PART", "DISSOLVE_LINES")
        arcpy.analysis.SpatialJoin(f"{out_fc_name}_Merged", f"{out_fc_name}_Dissolved", f"{out_fc_name}_SpatialJoin", "JOIN_ONE_TO_MANY", "KEEP_ALL", "", "INTERSECT")

        # Create a dictionary to store the shape_area values for each JOIN_FID
        shape_areas = {}

        # Use a SearchCursor to iterate over the features
        with arcpy.da.SearchCursor(f"{out_fc_name}_SpatialJoin", ["JOIN_FID", "shape_area"]) as cursor:
            for row in cursor:
                # Add the shape_area value to the list associated with the JOIN_FID
                shape_areas.setdefault(row[0], []).append(row[1])

        # Create a dictionary to store the mean and standard deviation of shape_area values for each JOIN_FID
        stats_areas = {join_fid: (statistics.mean(areas), statistics.stdev(areas)) for join_fid, areas in shape_areas.items() if len(areas) > 1}

        merge_src_dict = {}
        # Use a SearchCursor to iterate over the features again
        spatial_join_cursor = arcpy.da.SearchCursor(f"{out_fc_name}_SpatialJoin", ["OBJECTID", "JOIN_FID", "shape_area", "TARGET_FID_1", "MERGE_SRC"])
        for row in spatial_join_cursor:
            # If the absolute difference between the shape_area value and the mean is greater than 2 standard deviations, add the OBJECTID to the list
            join_fid = row[1]
            if join_fid in stats_areas:
                mean, stdev = stats_areas[join_fid]
                if abs(row[2] - mean) > 1.75 * stdev:
                    merge_src_dict.setdefault(row[4], []).append(row[3])
        del spatial_join_cursor

        # Iterate over the items in the dictionary
        for fc_path in merge_src_dict:
            # Use an UpdateCursor to iterate over the features in the feature class
            cursor = arcpy.da.UpdateCursor(fc_path, "OBJECTID")
            for row in cursor:
                
                # If the OBJECTID is in the list, delete the row
                if row[0] in merge_src_dict[fc_path]:
                    cursor.deleteRow()
            del cursor

        arcpy.Delete_management(f"{out_fc_name}_Merged")
        arcpy.Delete_management(f"{out_fc_name}_Dissolved")
        arcpy.Delete_management(f"{out_fc_name}_SpatialJoin")
        # Get a list of field names from the first input feature class
        field_names = [field.name for field in arcpy.ListFields(features_outputs[0])]
        field_names.append('SHAPE@JSON')

        # Copy the 40cm output cell size as the base final layer
        final_layer = f"{arcpy.env.workspace }\\{out_fc_name}"
        arcpy.AddMessage("Creating final layer...")

        # Choose the building output that has the closest cell size to the average cell size.
        closest_feature_output = min(features_outputs, key=lambda x: abs((float(x.split('_')[-1])/100) - chozen_cell_size))
        arcpy.AddMessage(f"Closest feature output: {closest_feature_output}")
        arcpy.CopyFeatures_management(closest_feature_output, final_layer)
        arcpy.AddMessage("Final layer created.")
        
        # Use an update cursor to delete features
        delete_areas_less_750_cursor = arcpy.da.UpdateCursor(final_layer, 'SHAPE@AREA')
        for row in delete_areas_less_750_cursor:
            # Check if the area is greater than 750 square meters
            if row[0] > max_area or row[0] < min_area:
                # Delete the feature
                delete_areas_less_750_cursor.deleteRow()

        # Sort the features_outputs based on their cell sizes
        features_outputs.sort(key=lambda x: abs(float(x.split('_')[-1]) - chozen_cell_size))

        arcpy.AddMessage(f"Processing the final {features_outputs}...")
        for features_output in features_outputs:
            if features_output != closest_feature_output:
                source_fc_name = features_output.split("\\")[-1]
                arcpy.AddMessage(f"Processing {source_fc_name}...")

                # Perform pairwise intersection between the base layer and the current output
                intersect_output = f"{arcpy.env.workspace }\\intersect_output"
                arcpy.analysis.PairwiseIntersect(
                    in_features=[final_layer, features_output],
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
                source_features_cursor = arcpy.da.SearchCursor(features_output, field_names)

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
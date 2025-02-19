import arcpy
import json
import zipfile
import os
import shutil
from arcpy.sa import *

inference_arguments = {
    "ObjectClassification": {
        "batch_size": 4,
        "score_threshold": 0.54,
        "test_time_augmentation": False
    },
    "ImageClassification": {
        "batch_size": 4,
        "padding": 64,
        "predict_background": True,
        "test_time_augmentation": False
    },
    "ChangeDetection": {
        "batch_size": 4,
        "padding": 64
    },
    "ObjectDetection": {
        "batch_size": 4,
        "exclude_pad_detections": False,
        "merge_policy": "mean",
        "nms_overlap": 0.1,
        "padding": 64,
        "threshold": 0.5,
        "tile_size": 256
    },
    "InstanceDetection": {
        "batch_size": 4,
        "exclude_pad_detections": False,
        "merge_policy": "mean",
        "nms_overlap": 0.1,
        "padding": 64,
        "threshold": 0.5,
        "tile_size": 256
    }
}
class Toolbox(object):
    def __init__(self):
        """Define the toolbox (the name of the toolbox is the name of the
        .pyt file)."""
        self.label = "Deep Learning process with boundaries"
        self.alias = "DeepLearningwithBoundaries"

        # List of tool classes associated with this toolbox
        self.tools = [
            ClassifyPixelsUsingDeepLearning,
            DetectObjectsUsingDeepLearning  # Add the new tool here
        ]

class ClassifyPixelsUsingDeepLearning(object):
    def __init__(self):
        self.label = "Classify Pixels Using Deep Learning"
        self.description = "Classify pixels using deep learning with additional processing geometry parameter."
        self.canRunInBackground = False
        self.error_message = None

    def getParameterInfo(self):
        params = []

        # Add all parameters for the Classify Pixels Using Deep Learning tool
        params.append(arcpy.Parameter(
            displayName="Input Raster",
            name="in_raster",
            datatype=["DERasterDataset", "GPRasterLayer", "DEMosaicDataset", "DEImageServer", 
                      "DEMapServer", "GPMapServerLayer", "GPInternetTiledLayer", "DEFolder", 
                      "GPFeatureLayer", "DEFeatureClass"],
            parameterType="Required",
            direction="Input"))

        params.append(arcpy.Parameter(
            displayName="Model Definition",
            name="model_definition",
            datatype="DEFile",
            parameterType="Required",
            direction="Input"))

        params.append(arcpy.Parameter(
            displayName="Output Classified Raster",
            name="out_classified_raster",
            datatype="DERasterDataset",
            parameterType="Required",
            direction="Output"))

        params.append(arcpy.Parameter(
            displayName="Processing Geometry",
            name="processing_geometry",
            datatype=["DEFeatureClass", "GPFeatureLayer"],
            parameterType="Required",
            direction="Input"))

        # Add a value table parameter for additional arguments
        params.append(arcpy.Parameter(
            displayName="Arguments",
            name="arguments",
            datatype="GPValueTable",
            parameterType="Optional",
            direction="Input"))

        params[-1].columns = [["GPString", "Name"], ["GPString", "Value"]]
        return params

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        self.error_message = None
        if parameters[1].altered:
            model_definition = parameters[1].valueAsText
            if model_definition and os.path.exists(model_definition):
                output_dir = os.path.join(os.path.dirname(model_definition), "extracted_model")
                if not os.path.exists(output_dir):
                    os.makedirs(output_dir)
                model_definition_basename = os.path.basename(model_definition)

                # Create a copy of the .dlpk file with a .zip extension
                copy_dlpk_path = os.path.join(output_dir, f"{model_definition_basename}")
                zip_path = os.path.join(output_dir, f"{model_definition_basename}.zip")

                # Create a copy of the dlpk file
                shutil.copy(model_definition, copy_dlpk_path)

                # Rename the .dlpk file to .zip if the zip file does not already exist
                if not os.path.exists(zip_path):
                    os.rename(copy_dlpk_path, zip_path)
                                
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(output_dir)
                
                # Look for the .emd file in the extracted contents
                emd_file = None
                for root, dirs, files in os.walk(output_dir):
                    for file in files:
                        if file.endswith('.emd'):
                            emd_file = os.path.join(root, file)
                            break
                    if emd_file:
                        break
                if emd_file:
                    # Read the .emd file
                    with open(emd_file, 'r', encoding='utf-8') as f:
                        model_info = json.load(f)
                        model_type = model_info.get('ModelType', '')
                        
                        # Populate arguments based on model type and name
                        arguments = []
                        
                        # Get the arguments for the model name
                        model_arguments = inference_arguments[model_type]
                        for arg in model_arguments:
                            value = model_arguments[arg]
                            if isinstance(value, bool):
                                value = str(value)  # Convert boolean to string "True" or "False"
                            arguments.append([arg, value])
                        
                        # Update the arguments parameter with the populated arguments
                        if not parameters[4].altered:
                            parameters[4].values = arguments
                else:
                    self.error_message = "No .emd file found in the extracted contents."
                
                # Clean up extracted files
                for root, dirs, files in os.walk(output_dir, topdown=False):
                    for name in files:
                        os.remove(os.path.join(root, name))
                    for name in dirs:
                        os.rmdir(os.path.join(root, name))
        return

    def updateMessages(self, parameters):
        if self.error_message:
            parameters[1].setErrorMessage(self.error_message)
        return

    def execute(self, parameters, messages):
        in_raster = parameters[0].valueAsText
        model_definition = parameters[1].valueAsText
        out_classified_raster = parameters[2].valueAsText
        processing_geometry = parameters[3].valueAsText
        arguments = parameters[4].values

        # Convert arguments to a dictionary, excluding deleted arguments
        arguments_dict = {arg[0]: arg[1] for arg in arguments if arg[1]}

        # Extract geodatabase path from the output classified raster
        gdb_path = os.path.dirname(out_classified_raster)

        # Calculate the area of the processing geometry using a search cursor
        area = 0
        extent = arcpy.Describe(processing_geometry).extent
        area = (extent.width * extent.height) / 1e6  # Convert square meters to square kilometers
        
        messages.addMessage(f"Processing geometry area: {area:.2f} square kilometers")
        
        # Calculate the tile area
        tile_size = int(arguments_dict.get("tile_size", 256))
        cell_size = arcpy.env.cellSize
        tile_area = (int(tile_size) * float(cell_size)) ** 2 / 1e6  # Convert to square kilometers

         # Calculate the tessellation area based on batch size and tile area
        batch_size = int(arguments_dict.get("batch_size", 4))
        tessellation_area = ((batch_size ** 4) * tile_area)

        messages.addMessage(
            f"Calculated tessellation area: {tessellation_area:.2f} square kilometers.\n"
            f"This area is determined based on the batch size and tile size specified in the model arguments.\n"
            f"The tessellation area represents the total area that will be processed in each batch during the object detection process.\n"
            f"Specifically, it is calculated as the area of a single tile (tile_size * cell_size)^2 multiplied by the number of tiles in a batch (batch_size^4).\n"
            f"For example, with a tile size of {tile_size} pixels and a batch size of {batch_size}, the tessellation area covers {batch_size ** 3} tiles."
        )

        if area > tessellation_area:
            messages.addMessage(f"Area is greater than {tessellation_area} square kilometers. Generating tessellation...")

            # Generate tessellation
            tessellation_output = os.path.join(gdb_path, "tessellation")
            arcpy.management.GenerateTessellation(
                tessellation_output, processing_geometry, "SQUARE", f"{tessellation_area} SquareKilometers")

            messages.addMessage("Tessellation generated. Performing spatial join...")

            # Clip tessellation with processing geometry
            clipped_tessellation_output = os.path.join(gdb_path, "clipped_tessellation")
            arcpy.analysis.Clip(
                in_features=tessellation_output,
                clip_features=processing_geometry,
                out_feature_class=clipped_tessellation_output,
                cluster_tolerance=None
            )

            messages.addMessage("Clipping completed. Extracting extents...")

            # Get extents for each polygon in the clipped tessellation output
            with arcpy.da.SearchCursor(clipped_tessellation_output, ["SHAPE@"]) as cursor:
                extents = [row[0].extent for row in cursor if row[0]]
            del cursor

            #Update feature class extent
            arcpy.management.RecalculateFeatureClassExtent(clipped_tessellation_output)

            messages.addMessage(f"Number of extents to process: {len(extents)}")

            # Run Classify Pixels Using Deep Learning for each extent
            output_rasters = []
            total_extents = len(extents)
            for i, extent in enumerate(extents, start=1):
                messages.addMessage(f"Processing extent {i} of {total_extents}...")
                arcpy.env.extent = extent
                temp_output = f"{gdb_path}\\classified_extent_{i}"
                
                
                formatted_arguments = ";".join([f"{key} {value}" for key, value in arguments_dict.items()])

                with arcpy.EnvManager(extent=extent, cellSize=arcpy.env.cellSize):
                    classified_raster = arcpy.ia.ClassifyPixelsUsingDeepLearning(
                        in_raster=in_raster,
                        in_model_definition=model_definition,
                        arguments=formatted_arguments,
                        processing_mode="PROCESS_AS_MOSAICKED_IMAGE",
                        out_classified_folder=None,
                        out_featureclass=None,
                        overwrite_attachments="NO_OVERWRITE",
                        use_pixelspace="NO_PIXELSPACE"
                    )
                    temp_output = arcpy.management.CreateUniqueName(temp_output, gdb_path)

                    classified_raster.save(temp_output)
                output_rasters.append(temp_output)

            messages.addMessage("Classified pixels for each extent. Merging output rasters...")

            # Merge all output rasters
            arcpy.management.MosaicToNewRaster(
                output_rasters, out_classified_raster, pixel_type="32_BIT_FLOAT")

            messages.addMessage("Output rasters merged. Cleaning up intermediate data...")

            # Clean up intermediate data
            arcpy.management.Delete(tessellation_output)
            arcpy.management.Delete(clipped_tessellation_output)
            for raster in output_rasters:
                arcpy.management.Delete(raster)

            messages.addMessage("Intermediate data cleaned up.")
        else:
            messages.addMessage(f"Area is less than or equal to {tessellation_area} square kilometers. Running classification directly...")

            # Use the extent of the processing geometry as the extent for the environment
            extent = arcpy.Describe(processing_geometry).extent
            arcpy.env.extent = extent

            # Run Classify Pixels Using Deep Learning directly
            with arcpy.EnvManager(extent=extent, cellSize=arcpy.env.cellSize):
                formatted_arguments = ";".join([f"{key} {value}" for key, value in arguments_dict.items()])
                classified_raster = arcpy.ia.ClassifyPixelsUsingDeepLearning(
                    in_raster=in_raster,
                    in_model_definition=model_definition,
                    arguments=formatted_arguments,
                    processing_mode="PROCESS_AS_MOSAICKED_IMAGE",
                    out_classified_folder=None,
                    out_featureclass=None,
                    overwrite_attachments="NO_OVERWRITE",
                    use_pixelspace="NO_PIXELSPACE"
                )
                classified_raster.save(out_classified_raster)
            messages.addMessage("Classification completed.")

        return

class DetectObjectsUsingDeepLearning(object):
    def __init__(self):
        self.label = "Detect Objects Using Deep Learning"
        self.description = "Detect objects using deep learning with additional processing geometry parameter."
        self.canRunInBackground = False
        self.error_message = None

    def getParameterInfo(self):
        params = []

        # Add all parameters for the Detect Objects Using Deep Learning tool
        params.append(arcpy.Parameter(
            displayName="Input Raster",
            name="in_raster",
            datatype=["DERasterDataset", "GPRasterLayer", "DEMosaicDataset", "DEImageServer", 
                      "DEMapServer", "GPMapServerLayer", "GPInternetTiledLayer", "DEFolder", 
                      "GPFeatureLayer", "DEFeatureClass"],
            parameterType="Required",
            direction="Input"))

        params.append(arcpy.Parameter(
            displayName="Model Definition",
            name="model_definition",
            datatype="DEFile",
            parameterType="Required",
            direction="Input"))

        params.append(arcpy.Parameter(
            displayName="Output Detected Objects",
            name="out_detected_objects",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Output"))

        params.append(arcpy.Parameter(
            displayName="Processing Geometry",
            name="processing_geometry",
            datatype=["DEFeatureClass", "GPFeatureLayer"],
            parameterType="Required",
            direction="Input"))

        # Add a value table parameter for additional arguments
        params.append(arcpy.Parameter(
            displayName="Arguments",
            name="arguments",
            datatype="GPValueTable",
            parameterType="Optional",
            direction="Input"))

        params[-1].columns = [["GPString", "Name"], ["GPString", "Value"]]

        # Add NMS related parameters
        params.append(arcpy.Parameter(
            displayName="Run Non-Maximum Suppression (NMS)",
            name="run_nms",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input"))

        params.append(arcpy.Parameter(
            displayName="Confidence Score Field",
            name="confidence_score_field",
            datatype="GPString",
            parameterType="Optional",
            direction="Input"))

        params.append(arcpy.Parameter(
            displayName="Class Value Field",
            name="class_value_field",
            datatype="GPString",
            parameterType="Optional",
            direction="Input"))

        params.append(arcpy.Parameter(
            displayName="Max Overlap Ratio",
            name="max_overlap_ratio",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input"))

        params.append(arcpy.Parameter(
            displayName="Use Pixel Space",
            name="use_pixelspace",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input"))
        return params

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        self.error_message = None
        if parameters[1].altered:
            model_definition = parameters[1].valueAsText
            if model_definition and os.path.exists(model_definition):
                output_dir = os.path.join(os.path.dirname(model_definition), "extracted_model")
                if not os.path.exists(output_dir):
                    os.makedirs(output_dir)
                model_definition_basename = os.path.basename(model_definition)

                # Create a copy of the .dlpk file with a .zip extension
                copy_dlpk_path = os.path.join(output_dir, f"{model_definition_basename}")
                zip_path = os.path.join(output_dir, f"{model_definition_basename}.zip")

                # Create a copy of the dlpk file
                shutil.copy(model_definition, copy_dlpk_path)

                # Rename the .dlpk file to .zip if the zip file does not already exist
                if not os.path.exists(zip_path):
                    os.rename(copy_dlpk_path, zip_path)
                                
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(output_dir)
                
                # Look for the .emd file in the extracted contents
                emd_file = None
                for root, dirs, files in os.walk(output_dir):
                    for file in files:
                        if file.endswith('.emd'):
                            emd_file = os.path.join(root, file)
                            break
                    if emd_file:
                        break
                if emd_file:
                    # Read the .emd file
                    with open(emd_file, 'r', encoding='utf-8') as f:
                        model_info = json.load(f)
                        model_type = model_info.get('ModelType', '')
                        
                        # Populate arguments based on model type and name
                        arguments = []
                        
                        # Get the arguments for the model name
                        model_arguments = inference_arguments[model_type]
                        for arg in model_arguments:
                            value = model_arguments[arg]
                            if isinstance(value, bool):
                                value = str(value)  # Convert boolean to string "True" or "False"
                            arguments.append([arg, value])
                        
                        # Update the arguments parameter with the populated arguments
                        if not parameters[4].altered:
                            parameters[4].values = arguments
                else:
                    self.error_message = "No .emd file found in the extracted contents."
                
                # Clean up extracted files
                for root, dirs, files in os.walk(output_dir, topdown=False):
                    for name in files:
                        os.remove(os.path.join(root, name))
                    for name in dirs:
                        os.rmdir(os.path.join(root, name))

        # Dynamically show NMS-related parameters
        if parameters[5].value:
            parameters[6].enabled = True
            parameters[7].enabled = True
            parameters[8].enabled = True
        else:
            parameters[6].enabled = False
            parameters[7].enabled = False
            parameters[8].enabled = False

        # Set default values for confidence_score_field and class_value_field
        if not parameters[6].altered:
            parameters[6].value = "confidence"
        if not parameters[7].altered:
            parameters[7].value = "classvalue"
        return

    def updateMessages(self, parameters):
        if self.error_message:
            parameters[1].setErrorMessage(self.error_message)
        return

    def execute(self, parameters, messages):
        in_raster = parameters[0].valueAsText
        model_definition = parameters[1].valueAsText
        out_detected_objects = parameters[2].valueAsText
        processing_geometry = parameters[3].valueAsText
        arguments = parameters[4].values
        run_nms = parameters[5].value
        confidence_score_field = parameters[6].valueAsText
        class_value_field = parameters[7].valueAsText
        max_overlap_ratio = parameters[8].value
        use_pixelspace = parameters[9].value

        # Convert arguments to a dictionary, excluding deleted arguments
        arguments_dict = {arg[0]: arg[1] for arg in arguments if arg[1]}

        # Extract geodatabase path from the output detected objects
        gdb_path = os.path.dirname(out_detected_objects)
        
        # Calculate the area of the processing geometry using a search cursor
        area = 0
        extent = arcpy.Describe(processing_geometry).extent
        area = (extent.width * extent.height) / 1e6  # Convert square meters to square kilometers

        messages.addMessage(f"Processing geometry extent: {area:.2f} square kilometers")
        
        # Calculate the tile area
        tile_size = int(arguments_dict.get("tile_size", 256))
        cell_size = arcpy.env.cellSize
        tile_area = (int(tile_size) * float(cell_size)) ** 2 / 1e6  # Convert to square kilometers

         # Calculate the tessellation area based on batch size and tile area
        batch_size = int(arguments_dict.get("batch_size", 4))
        tessellation_area = ((batch_size ** 4) * tile_area)

        messages.addMessage(
            f"Calculated tessellation area: {tessellation_area:.2f} square kilometers.\n"
            f"This area is determined based on the batch size and tile size specified in the model arguments.\n"
            f"The tessellation area represents the total area that will be processed in each batch during the object detection process.\n"
            f"Specifically, it is calculated as the area of a single tile (tile_size * cell_size)^2 multiplied by the number of tiles in a batch (batch_size^4).\n"
            f"For example, with a tile size of {tile_size} pixels and a batch size of {batch_size}, the tessellation area covers {batch_size ** 3} tiles."
        )

        if area > tessellation_area:
            messages.addMessage(f"Area is greater than {tessellation_area} square kilometers. Generating tessellation...")

            # Generate tessellation
            tessellation_output = os.path.join(gdb_path, "tessellation")
            arcpy.management.GenerateTessellation(
                tessellation_output, processing_geometry, "SQUARE", f"{tessellation_area} SquareKilometers")

            messages.addMessage("Tessellation generated. Performing spatial join...")
            # Clip tessellation with processing geometry
            clipped_tessellation_output = os.path.join(gdb_path, "clipped_tessellation")
            arcpy.analysis.Clip(
                in_features=tessellation_output,
                clip_features=processing_geometry,
                out_feature_class=clipped_tessellation_output,
                cluster_tolerance=None
            )

            #Update feature class extent
            arcpy.management.RecalculateFeatureClassExtent(clipped_tessellation_output)

            messages.addMessage("Clipping completed. Extracting extents...")

            # Get extents for each polygon in the clipped tessellation output
            with arcpy.da.SearchCursor(clipped_tessellation_output, ["SHAPE@"]) as cursor:
                extents = [row[0].extent for row in cursor if row[0]]
            del cursor

            messages.addMessage(f"Number of extents to process: {len(extents)}")

            # Run Detect Objects Using Deep Learning for each extent
            output_features = []
            total_extents = len(extents)
            for i, extent in enumerate(extents, start=1):
                messages.addMessage(f"Processing extent {i} of {total_extents}...")
                arcpy.env.extent = extent
                #messages.addMessage(f"Extent: {extent.XMin}, {extent.YMin}, {extent.XMax}, {extent.YMax}, {extent.spatialReference.name}")
                temp_output = f"{gdb_path}\\detected_extent_{i}"
            
                formatted_arguments = ";".join([f"{key} {value}" for key, value in arguments_dict.items()])
                with arcpy.EnvManager(extent=extent, cellSize=arcpy.env.cellSize):
                    arcpy.ia.DetectObjectsUsingDeepLearning(
                        in_raster=in_raster,
                        out_detected_objects=temp_output,
                        in_model_definition=model_definition,
                        arguments=formatted_arguments,
                        run_nms="NMS" if run_nms else "NO_NMS",
                        confidence_score_field=confidence_score_field if run_nms else None,
                        class_value_field=class_value_field if run_nms else None,
                        max_overlap_ratio=max_overlap_ratio if run_nms else None,
                        processing_mode="PROCESS_AS_MOSAICKED_IMAGE",
                        use_pixelspace="PIXELSPACE" if use_pixelspace else "NO_PIXELSPACE"
                    )
                output_features.append(temp_output)

            messages.addMessage("Detected objects for each extent. Merging output features...")

            # Merge all output features
            arcpy.management.Merge(output_features, out_detected_objects)

            messages.addMessage("Output features merged. Cleaning up intermediate data...")

            # Clean up intermediate data
            arcpy.management.Delete(tessellation_output)
            arcpy.management.Delete(clipped_tessellation_output)
            
            for feature in output_features:
                arcpy.management.Delete(feature)

            messages.addMessage("Intermediate data cleaned up.")
        else:
            messages.addMessage(f"Area is less than or equal to {tessellation_area} square kilometers. Running detection directly...")

            # Use the extent of the processing geometry as the extent for the environment
            extent = arcpy.Describe(processing_geometry).extent
            arcpy.env.extent = extent

            # Run Detect Objects Using Deep Learning directly
            with arcpy.EnvManager(extent=extent, cellSize=arcpy.env.cellSize):
                formatted_arguments = ";".join([f"{key} {value}" for key, value in arguments_dict.items()])
                arcpy.ia.DetectObjectsUsingDeepLearning(
                    in_raster=in_raster,
                    out_detected_objects=out_detected_objects,
                    in_model_definition=model_definition,
                    arguments=formatted_arguments,
                    run_nms="NMS" if run_nms else "NO_NMS",
                    confidence_score_field=confidence_score_field if run_nms else None,
                    class_value_field=class_value_field if run_nms else None,
                    max_overlap_ratio=max_overlap_ratio if run_nms else None,
                    processing_mode="PROCESS_AS_MOSAICKED_IMAGE",
                    use_pixelspace="PIXELSPACE" if use_pixelspace else "NO_PIXELSPACE"
                )

            messages.addMessage("Detection completed.")

        return

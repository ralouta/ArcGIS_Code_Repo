import arcpy
import json
import zipfile
import os
import shutil
from arcpy.sa import *

inference_arguments = {
    "Classify Objects": {
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
    "Detect Change": {
        "batch_size": 4,
        "padding": 64
    },
    "Detect Objects": {
        "batch_size": 4,
        "exclude_pad_detections": False,
        "merge_policy": "mean",
        "nms_overlap": 0.1,
        "output_classified_raster": "",
        "padding": 64,
        "threshold": 0.5,
        "tile_size": 256
    }
}
class Toolbox(object):
    def __init__(self):
        """Define the toolbox (the name of the toolbox is the name of the
        .pyt file)."""
        self.label = "Deep Learning Tools process within boundaries"
        self.alias = "Toolbox for Deep Learning tools to process within grids that overlap boundaries. Grids are hardcoded to be 100 square kilometers."

        # List of tool classes associated with this toolbox
        self.tools = [
            ClassifyPixelsUsingDeepLearning  # Add the new tool here
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


        # Add other parameters as needed...

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

        # Convert arguments to a dictionary
        arguments_dict = {arg[0]: arg[1] for arg in arguments}

        # Extract geodatabase path from the output classified raster
        gdb_path = os.path.dirname(out_classified_raster)

        # Calculate the area of the processing geometry using a search cursor
        area = 0
        with arcpy.da.SearchCursor(processing_geometry, ["SHAPE@AREA"]) as cursor:
            for row in cursor:
                area += row[0] / 1e6  # Convert square meters to square kilometers

        messages.addMessage(f"Processing geometry area: {area:.2f} square kilometers")

        if area > 100:
            messages.addMessage("Area is greater than 100 square kilometers. Generating tessellation...")

            # Generate tessellation
            tessellation_output = os.path.join(gdb_path, "tessellation")
            arcpy.management.GenerateTessellation(
                tessellation_output, processing_geometry, "SQUARE", "100 SquareKilometers")

            messages.addMessage("Tessellation generated. Performing spatial join...")

            # Spatial join tessellation with processing geometry
            spatial_join_output = os.path.join(gdb_path, "spatial_join")
            arcpy.analysis.SpatialJoin(tessellation_output, processing_geometry, spatial_join_output)

            messages.addMessage("Spatial join completed. Extracting extents...")

            # Get extents for each polygon in the spatial join output
            with arcpy.da.SearchCursor(spatial_join_output, ["SHAPE@"], where_clause="Join_Count > 0") as cursor:
                extents = [row[0].extent for row in cursor if row[0]]

            messages.addMessage(f"Number of extents to process: {len(extents)}")

            # Run Classify Pixels Using Deep Learning for each extent
            output_rasters = []
            total_extents = len(extents)
            for i, extent in enumerate(extents, start=1):
                messages.addMessage(f"Processing extent {i} of {total_extents}...")
                arcpy.env.extent = extent
                temp_output = os.path.join(gdb_path, f"classified_extent_{i}")
                
                formatted_arguments = ";".join([f"{key} {value}" for key, value in arguments_dict.items()])

                with arcpy.EnvManager(extent=extent):
                    # Convert arguments_dict to the required format
                    classified_raster = arcpy.ia.ClassifyPixelsUsingDeepLearning(
                        in_raster=in_raster,
                        in_model_definition=model_definition,
                        arguments = formatted_arguments,
                        processing_mode="PROCESS_AS_MOSAICKED_IMAGE",
                        out_classified_folder=None,
                        out_featureclass=None,
                        overwrite_attachments="NO_OVERWRITE",
                        use_pixelspace="NO_PIXELSPACE"
                    )
                messages.addMessage(f"Saving classified pixels for extent {i}...")
                classified_raster.save(temp_output)
                output_rasters.append(temp_output)

            messages.addMessage("Classified pixels for each extent. Merging output rasters...")

            # Merge all output rasters
            arcpy.management.MosaicToNewRaster(
                output_rasters, out_classified_raster, pixel_type="32_BIT_FLOAT")

            messages.addMessage("Output rasters merged. Cleaning up intermediate data...")

            # Clean up intermediate data
            arcpy.management.Delete(tessellation_output)
            arcpy.management.Delete(spatial_join_output)
            for raster in output_rasters:
                arcpy.management.Delete(raster)

            messages.addMessage("Intermediate data cleaned up.")
        else:
            messages.addMessage("Area is less than or equal to 100 square kilometers. Running classification directly...")

            # Run Classify Pixels Using Deep Learning directly
            with arcpy.EnvManager():
                    # Convert arguments_dict to the required format
                    classified_raster = arcpy.ia.ClassifyPixelsUsingDeepLearning(
                        in_raster=in_raster,
                        in_model_definition=model_definition,
                        arguments = formatted_arguments,
                        processing_mode="PROCESS_AS_MOSAICKED_IMAGE",
                        out_classified_folder=None,
                        out_featureclass=None,
                        overwrite_attachments="NO_OVERWRITE",
                        use_pixelspace="NO_PIXELSPACE"
                    )
                    classified_raster.save(out_classified_raster)
            messages.addMessage("Classification completed.")

        return

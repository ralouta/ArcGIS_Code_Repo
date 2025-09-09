import arcpy
import math
import os

class Toolbox(object):
    def __init__(self):
        # Set toolbox label and alias
        self.label = "Compactness Toolbox"
        self.alias = "compactnesstbx"
        # Register the ComputeCompactness tool
        self.tools = [ComputeCompactness]

class ComputeCompactness(object):
    def __init__(self):
        # Set tool label and description
        self.label = "Compute and Filter by Compactness"
        self.description = "Calculates compactness ratio and removes features below a threshold."

    def getParameterInfo(self):
        params = []

        # Define input polygon features parameter
        param0 = arcpy.Parameter(
            displayName="Input Polygon Features",
            name="in_features",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input"
        )

        # Define output feature class parameter
        param1 = arcpy.Parameter(
            displayName="Output Feature Class",
            name="out_features",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Output"
        )

        # Define compactness threshold parameter (optional, default 0.4)
        param2 = arcpy.Parameter(
            displayName="Compactness Threshold",
            name="compactness_threshold",
            datatype="Double",
            parameterType="Optional",
            direction="Input"
        )
        param2.value = 0.4  # default value

        params.extend([param0, param1, param2])
        return params

    def execute(self, parameters, messages):
        in_fc = parameters[0].valueAsText
        out_fc = parameters[1].valueAsText
        threshold = float(parameters[2].value)

        # Step 1: Copy features
        arcpy.CopyFeatures_management(in_fc, out_fc)

        # Add the compactness_ratio field if it doesn't exist
        field_names = [f.name for f in arcpy.ListFields(out_fc)]
        if "compactness_ratio" not in field_names:
            arcpy.AddField_management(out_fc, "compactness_ratio", "DOUBLE")

        # Step 2: Calculate compactness and filter features
        with arcpy.da.UpdateCursor(out_fc, ["SHAPE@", "compactness_ratio"]) as cursor:
            for row in cursor:
                geometry = row[0]
                # Calculate area and perimeter
                area = geometry.area
                perimeter = geometry.length
                # Avoid division by zero
                if perimeter == 0:
                    compactness = 0
                else:
                    # Calculate compactness ratio
                    compactness = (4 * math.pi * area) / (perimeter ** 2)
                row[1] = compactness
                # Delete feature if compactness is below the threshold
                if compactness < threshold:
                    cursor.deleteRow()
                else:
                    cursor.updateRow(row)

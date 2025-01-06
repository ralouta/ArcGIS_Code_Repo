import arcpy
from arcpy.sa import *

class Toolbox(object):
    def __init__(self):
        """Define the toolbox (the name of the toolbox is the name of the
        .pyt file)."""
        self.label = "Post Deep Learning Workflows"
        self.alias = "Toolbox for post-processing deep learning results"

        # List of tool classes associated with this toolbox
        self.tools = [PostDeepLearningBuildingsWorkflows, PostDeepLearningRoadsWorkflows, PostDeepLearningTreeWorkflows]

def raster_to_polygon(input_raster, field_name, unique_value, messages):
    messages.addMessage("Starting raster to polygon conversion...")

    # Set the output coordinate system to match the input raster
    spatial_ref = arcpy.Describe(input_raster).spatialReference
    arcpy.env.outputCoordinateSystem = spatial_ref

    # Convert raster to polygon
    messages.addMessage("Converting raster to polygon...")
    polygon_fc = "in_memory/polygon_fc"
    arcpy.RasterToPolygon_conversion(input_raster, polygon_fc, "NO_SIMPLIFY", field_name)
    messages.addMessage("Raster to polygon conversion completed.")

    # Delete polygons with field values not equal to the unique value
    messages.addMessage(f"Deleting polygons with field values not equal to {unique_value}...")
    with arcpy.da.UpdateCursor(polygon_fc, [field_name], f"{field_name} <> '{unique_value}'") as cursor:
        for row in cursor:
            cursor.deleteRow()
    messages.addMessage(f"Polygons with field values not equal to {unique_value} deleted.")

    return polygon_fc

class PostDeepLearningBuildingsWorkflows(object):
    def __init__(self):
        self.label = "Post Processing Buildings from Raster Output"
        self.description = "Toolbox for post-processing deep learning results"
        self.canRunInBackground = False

    def getParameterInfo(self):
        params = []

        input_raster = arcpy.Parameter(
            displayName="Input Raster",
            name="in_raster",
            datatype=["DEMapServer", "GPRasterDataLayer", "DEImageServer", "DEMosaicDataset",
                      "DERasterDataset", "GPRasterLayer", "GPRasterDataLayer"],
            parameterType="Required",
            direction="Input"
        )
        params.append(input_raster)

        field_name = arcpy.Parameter(
            displayName="Field Name for Raster to Polygon",
            name="field_name",
            datatype="Field",
            parameterType="Required",
            direction="Input"
        )
        field_name.parameterDependencies = [input_raster.name]
        params.append(field_name)

        unique_value = arcpy.Parameter(
            displayName="Unique Value of Selected Field",
            name="unique_value",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue=True
        )
        unique_value.parameterDependencies = [field_name.name]
        params.append(unique_value)

        output_feature_class = arcpy.Parameter(
            displayName="Output Feature Class",
            name="output_feature_class",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Output"
        )
        params.append(output_feature_class)

        return params

    def updateParameters(self, parameters):
        if parameters[1].altered:
            field_name = parameters[1].valueAsText
            input_raster = parameters[0].valueAsText
            if field_name and input_raster:
                unique_values = set()
                with arcpy.da.SearchCursor(input_raster, [field_name]) as cursor:
                    for row in cursor:
                        unique_values.add(row[0])
                parameters[2].filter.list = sorted(unique_values)
        return

    def execute(self, parameters, messages):
        input_raster = parameters[0].valueAsText
        field_name = parameters[1].valueAsText
        unique_value = parameters[2].valueAsText
        output_feature_class = parameters[3].valueAsText

        messages.addMessage("Starting the post-processing workflow...")

        polygon_fc = raster_to_polygon(input_raster, field_name, unique_value, messages)

        # Repair polygon geometry
        messages.addMessage("Repairing polygon geometry...")
        arcpy.RepairGeometry_management(polygon_fc)
        messages.addMessage("Polygon geometry repaired.")

        # Apply pairwise buffer with -125 cm
        messages.addMessage("Applying pairwise buffer with -125 cm...")
        buffer_fc = "in_memory/buffer_fc"
        arcpy.analysis.PairwiseBuffer(polygon_fc, buffer_fc, "-150 Centimeters")
        messages.addMessage("Pairwise buffer applied.")

        # Run pairwise dissolve
        messages.addMessage("Running pairwise dissolve...")
        dissolve_fc = "in_memory/dissolve_fc"
        arcpy.analysis.PairwiseDissolve(buffer_fc, dissolve_fc)
        messages.addMessage("Pairwise dissolve completed.")

        # Convert multipart to single part
        messages.addMessage("Converting multipart to single part...")
        singlepart_fc = "in_memory/singlepart_fc"
        arcpy.MultipartToSinglepart_management(dissolve_fc, singlepart_fc)
        messages.addMessage("Multipart to single part conversion completed.")

        # Apply a 125 cm positive buffer
        messages.addMessage("Applying a 125 cm positive buffer...")
        buffer_positive_fc = "in_memory/buffer_positive_fc"
        arcpy.analysis.PairwiseBuffer(singlepart_fc, buffer_positive_fc, "150 Centimeters")
        messages.addMessage("Positive buffer applied.")

        # Fill gaps with max gap area of 25 square meters
        messages.addMessage("Filling gaps with max gap area of 25 square meters...")
        filled_gaps_fc = "in_memory/filled_gaps_fc"
        arcpy.management.EliminatePolygonPart(buffer_positive_fc, filled_gaps_fc, "AREA", part_area="25 SquareMeters")
        messages.addMessage("Gaps filled.")

        # Use search cursor to filter polygons by area
        messages.addMessage("Filtering polygons by area...")
        feature_class_1 = "in_memory/feature_class_1"
        feature_class_2 = "in_memory/feature_class_2"
        feature_class_3 = "in_memory/feature_class_3"
        feature_class_4 = "in_memory/feature_class_4"

        arcpy.CreateFeatureclass_management("in_memory", "feature_class_1", "POLYGON", template=filled_gaps_fc)
        arcpy.CreateFeatureclass_management("in_memory", "feature_class_2", "POLYGON", template=filled_gaps_fc)
        arcpy.CreateFeatureclass_management("in_memory", "feature_class_3", "POLYGON", template=filled_gaps_fc)
        arcpy.CreateFeatureclass_management("in_memory", "feature_class_4", "POLYGON", template=filled_gaps_fc)

        with arcpy.da.SearchCursor(filled_gaps_fc, ["SHAPE@", "SHAPE@AREA"]) as cursor:
            with arcpy.da.InsertCursor(feature_class_1, ["SHAPE@"]) as cursor_1, arcpy.da.InsertCursor(feature_class_2, ["SHAPE@"]) as cursor_2, arcpy.da.InsertCursor(feature_class_3, ["SHAPE@"]) as cursor_3, arcpy.da.InsertCursor(feature_class_4, ["SHAPE@"]) as cursor_4:
                for row in cursor:
                    if 4 <= row[1] <= 100:
                        cursor_1.insertRow([row[0]])
                    elif 100 < row[1] <= 1000:
                        cursor_2.insertRow([row[0]])
                    elif 1000 < row[1] <= 5000:
                        cursor_3.insertRow([row[0]])
                    else:
                        cursor_4.insertRow([row[0]])
        messages.addMessage("Polygons filtered by area.")

        # Regularize building footprints
        messages.addMessage("Regularizing building footprints for feature class 1 (area range: 4 - 100 square meters)...")
        regularized_fc_1 = "in_memory/regularized_fc_1"
        arcpy.ddd.RegularizeBuildingFootprint(feature_class_1, regularized_fc_1, "RIGHT_ANGLES_AND_DIAGONALS", 0.5)
        messages.addMessage("Building footprints for feature class 1 regularized.")

        messages.addMessage("Regularizing building footprints for feature class 2 (area range: 100 - 1000 square meters)...")
        regularized_fc_2 = "in_memory/regularized_fc_2"
        arcpy.ddd.RegularizeBuildingFootprint(feature_class_2, regularized_fc_2, "RIGHT_ANGLES_AND_DIAGONALS", 2.5)
        messages.addMessage("Building footprints for feature class 2 regularized.")

        messages.addMessage("Regularizing building footprints for feature class 3 (area range: 1000 - 5000 square meters)...")
        regularized_fc_3 = "in_memory/regularized_fc_3"
        arcpy.ddd.RegularizeBuildingFootprint(feature_class_3, regularized_fc_3, "RIGHT_ANGLES_AND_DIAGONALS", 5)
        messages.addMessage("Building footprints for feature class 3 regularized.")

        messages.addMessage("Regularizing building footprints for feature class 4 (area range: > 5000 square meters)...")
        regularized_fc_4 = "in_memory/regularized_fc_4"
        arcpy.ddd.RegularizeBuildingFootprint(feature_class_4, regularized_fc_4, "RIGHT_ANGLES_AND_DIAGONALS", 7.5)
        messages.addMessage("Building footprints for feature class 4 regularized.")

        # Merge both layers
        messages.addMessage("Merging both feature classes...")
        arcpy.management.Merge([regularized_fc_1, regularized_fc_2, regularized_fc_3, regularized_fc_4], output_feature_class)
        messages.addMessage("Feature classes merged.")

        # Delete intermediate layers
        messages.addMessage("Deleting intermediate layers...")
        arcpy.management.Delete([polygon_fc, buffer_fc, dissolve_fc, singlepart_fc, buffer_positive_fc, filled_gaps_fc, feature_class_1, feature_class_2, feature_class_3, feature_class_4, regularized_fc_1, regularized_fc_2, regularized_fc_3, regularized_fc_4])
        messages.addMessage("Intermediate layers deleted.")

        messages.addMessage("Post-processing workflow completed successfully.")

        return
    

class PostDeepLearningRoadsWorkflows(object):
    def __init__(self):
        self.label = "Post Processing Roads from Raster Output"
        self.description = "Toolbox for post-processing deep learning results"
        self.canRunInBackground = False

    def getParameterInfo(self):
        params = []

        input_raster = arcpy.Parameter(
            displayName="Input Raster",
            name="in_raster",
            datatype=["DEMapServer", "GPRasterDataLayer", "DEImageServer", "DEMosaicDataset",
                      "DERasterDataset", "GPRasterLayer", "GPRasterDataLayer"],
            parameterType="Required",
            direction="Input"
        )
        params.append(input_raster)

        field_name = arcpy.Parameter(
            displayName="Field Name for Raster to Polygon",
            name="field_name",
            datatype="Field",
            parameterType="Required",
            direction="Input"
        )
        field_name.parameterDependencies = [input_raster.name]
        params.append(field_name)

        unique_values_param = arcpy.Parameter(
            displayName="Unique Value of Selected Field",
            name="unique_value",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue=True
        )
        unique_values_param.parameterDependencies = [field_name.name]
        params.append(unique_values_param)

        output_feature_class = arcpy.Parameter(
            displayName="Output Feature Class",
            name="output_feature_class",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Output"
        )
        params.append(output_feature_class)

        return params

    def updateParameters(self, parameters):
        if parameters[1].altered:
            field_name = parameters[1].valueAsText
            input_raster = parameters[0].valueAsText
            if field_name and input_raster:
                unique_values = set()
                with arcpy.da.SearchCursor(input_raster, [field_name]) as cursor:
                    for row in cursor:
                        unique_values.add(row[0])
                parameters[2].filter.list = sorted(unique_values)
        return

    def execute(self, parameters, messages):
        input_raster = parameters[0].valueAsText
        field_name = parameters[1].valueAsText
        unique_value = parameters[2].valueAsText
        output_feature_class = parameters[3].valueAsText

        messages.addMessage("Starting the post-processing workflow...")

        polygon_fc = raster_to_polygon(input_raster, field_name, unique_value, messages)

        # Smooth the polygons
        messages.addMessage("Smoothing the polygons with 25 meters tolerance...")
        smoothed_fc = "in_memory/smoothed_fc"
        arcpy.cartography.SmoothPolygon(polygon_fc, smoothed_fc, "PAEK", 25)
        messages.addMessage("Polygons smoothed.")

        # Eliminate polygon parts with area less than 50 square meters
        messages.addMessage("Eliminating polygon parts with area less than 50 square meters...")
        eliminated_fc = "in_memory/eliminated_fc"
        arcpy.management.EliminatePolygonPart(smoothed_fc, eliminated_fc, "AREA", part_area="50 SquareMeters")
        messages.addMessage("Polygon parts eliminated.")

        # Delete polygons with area less than 50 square meters
        messages.addMessage("Deleting polygons with area less than 50 square meters...")
        with arcpy.da.UpdateCursor(eliminated_fc, ["SHAPE@AREA"]) as cursor:
            for row in cursor:
                if row[0] < 50:
                    cursor.deleteRow()
        messages.addMessage("Polygons with area less than 50 square meters deleted.")

        # Convert polygons to centerlines
        messages.addMessage("Converting polygons to centerlines...")
        centerline_fc = "in_memory/centerline_fc"
        arcpy.topographic.PolygonToCenterline(eliminated_fc, centerline_fc)
        messages.addMessage("Polygons converted to centerlines.")

        # Extend the centerlines by 50 meters
        messages.addMessage("Extending the centerlines by 50 meters...")
        arcpy.edit.ExtendLine(centerline_fc, "50 Meters", "EXTENSION")
        messages.addMessage("Centerlines extended.")

        # Convert polygons to lines
        messages.addMessage("Converting polygons to lines...")
        polygon_to_line_fc = "in_memory/polygon_to_line_fc"
        arcpy.PolygonToLine_management(eliminated_fc, polygon_to_line_fc)
        messages.addMessage("Polygons converted to lines.")

        # Perform Near analysis
        messages.addMessage("Performing Near analysis...")
        arcpy.analysis.Near(centerline_fc, polygon_to_line_fc, search_radius="10 Meters", location="NO_LOCATION", angle="NO_ANGLE", method="PLANAR", field_names="NEAR_FID NEAR_FID;NEAR_DIST NEAR_DIST", distance_unit="Meters")
        messages.addMessage("Near analysis completed.")

        # Smooth the centerlines
        messages.addMessage("Smoothing the centerlines...")
        smoothed_line_fc = output_feature_class
        arcpy.cartography.SmoothLine(centerline_fc, smoothed_line_fc, algorithm="PAEK", tolerance="100 Meters", endpoint_option="FIXED_CLOSED_ENDPOINT", error_option="NO_CHECK", in_barriers=None)
        messages.addMessage("Centerlines smoothed.")

        # Add and calculate a field for road width based on NEAR_DIST field values
        messages.addMessage("Adding and calculating a field for road width...")
        arcpy.AddField_management(smoothed_line_fc, "RoadWidth", "DOUBLE")
        with arcpy.da.UpdateCursor(smoothed_line_fc, ["NEAR_DIST", "RoadWidth"]) as cursor:
            for row in cursor:
                if row[0] <= 2.5:
                    row[1] = 2.5
                elif row[0] <= 5:
                    row[1] = 5
                else:
                    row[1] = 10
                cursor.updateRow(row)
        messages.addMessage("Field for road width added and calculated.")

        messages.addMessage("Post-processing workflow completed successfully.")

        return

class PostDeepLearningTreeWorkflows(object):
    def __init__(self):
        self.label = "Post Processing Trees from Raster Output"
        self.description = "Toolbox for post-processing deep learning results"
        self.canRunInBackground = False

    def getParameterInfo(self):
        params = []

        input_rasters = arcpy.Parameter(
            displayName="Input Rasters",
            name="in_rasters",
            datatype=["DEMapServer", "GPRasterDataLayer", "DEImageServer", "DEMosaicDataset",
                      "DERasterDataset", "GPRasterLayer", "GPRasterDataLayer"],
            parameterType="Required",
            direction="Input",
            multiValue=True
        )
        params.append(input_rasters)

        field_name = arcpy.Parameter(
            displayName="Field Name for Raster to Polygon",
            name="field_name",
            datatype="Field",
            parameterType="Required",
            direction="Input"
        )
        field_name.parameterDependencies = [input_rasters.name]
        params.append(field_name)

        unique_value = arcpy.Parameter(
            displayName="Unique Value of Selected Field",
            name="unique_value",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue=False
        )
        unique_value.parameterDependencies = [field_name.name]
        params.append(unique_value)

        output_feature_class = arcpy.Parameter(
            displayName="Output Feature Class",
            name="output_feature_class",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Output"
        )
        params.append(output_feature_class)

        return params

    def updateParameters(self, parameters):
        if parameters[1].altered:
            field_name = parameters[1].valueAsText
            input_rasters = parameters[0].values
            if field_name and input_rasters:
                unique_values = set()
                for input_raster in input_rasters:
                    with arcpy.da.SearchCursor(input_raster, [field_name]) as cursor:
                        for row in cursor:
                            unique_values.add(row[0])
                parameters[2].filter.list = sorted(unique_values)
        return

    def execute(self, parameters, messages):
        input_rasters = parameters[0].values
        field_name = parameters[1].valueAsText
        unique_value = parameters[2].valueAsText
        output_feature_class = parameters[3].valueAsText

        messages.addMessage("Starting the post-processing workflow...")

        final_output_fc = "in_memory/final_output_fc"
        first_iteration = True
        for input_raster in input_rasters:
            polygon_fc = raster_to_polygon(input_raster, field_name, unique_value, messages)
            # Repair polygon geometry
            messages.addMessage("Repairing polygon geometry...")
            arcpy.RepairGeometry_management(polygon_fc)
            messages.addMessage("Polygon geometry repaired.")

            # Apply a 10 cm buffer
            messages.addMessage("Applying a 10 cm buffer...")
            buffer_fc = "in_memory/buffer_fc"
            arcpy.analysis.PairwiseBuffer(polygon_fc, buffer_fc, "10 Centimeters")
            messages.addMessage("10 cm buffer applied.")

            # Split the polygon feature class into two based on area
            messages.addMessage("Splitting the polygon feature class into two based on area...")

            tree_area_fc_1 = "in_memory/tree_area_fc_1"
            tree_area_fc_2 = "in_memory/tree_area_fc_2"

            arcpy.CreateFeatureclass_management("in_memory", "tree_area_fc_1", "POLYGON", template=buffer_fc)
            arcpy.CreateFeatureclass_management("in_memory", "tree_area_fc_2", "POLYGON", template=buffer_fc)

            with arcpy.da.SearchCursor(buffer_fc, ["SHAPE@", "SHAPE@AREA"]) as cursor:
                with arcpy.da.InsertCursor(tree_area_fc_1, ["SHAPE@"]) as cursor_1, arcpy.da.InsertCursor(tree_area_fc_2, ["SHAPE@"]) as cursor_2:
                    for row in cursor:
                        if row[1] <= 7.5:
                            cursor_1.insertRow([row[0]])
                        else:
                            cursor_2.insertRow([row[0]])
            del cursor, cursor_1, cursor_2  # Clean up cursor objects

            messages.addMessage("Polygon feature class split into two based on area.")
            # Minimum bounding geometry
            messages.addMessage("Applying minimum bounding geometry...")
            mbg_fc = "in_memory/mbg_fc"
            arcpy.management.MinimumBoundingGeometry(tree_area_fc_2, mbg_fc, "RECTANGLE_BY_AREA", "None")
            messages.addMessage("Minimum bounding geometry applied.")

            # Generate tessellation
            messages.addMessage("Generating tessellation...")
            tessellation_fc = "in_memory/tessellation_fc"
            extent = arcpy.Describe(tree_area_fc_2).extent
            if extent.XMin is None or extent.YMin is None or extent.XMax is None or extent.YMax is None:
                raise ValueError("Invalid extent values found.")
            messages.addMessage("Extent values: XMin: {0}, YMin: {1}, XMax: {2}, YMax: {3}".format(extent.XMin, extent.YMin, extent.XMax, extent.YMax))
            arcpy.management.GenerateTessellation(tessellation_fc, extent, "SQUARE", "5 SquareMeters")
            messages.addMessage("Tessellation generated.")

            # Pairwise intersect
            messages.addMessage("Performing pairwise intersect...")
            intersect_fc = "in_memory/intersect_fc"
            arcpy.analysis.PairwiseIntersect([tessellation_fc, tree_area_fc_2], intersect_fc, join_attributes="ALL", cluster_tolerance=None, output_type="INPUT")
            messages.addMessage("Pairwise intersect completed.")

            # Merge clip_fc with tree_area_fc_1
            messages.addMessage("Merging clip_fc with tree_area_fc_1...")
            merged_fc = "in_memory/merged_fc"
            arcpy.management.Merge([intersect_fc, tree_area_fc_1], merged_fc)
            messages.addMessage("Merge completed.")
            
            # Convert multipart to single part
            messages.addMessage("Converting multipart to single part...")
            singlepart_fc = "in_memory/singlepart_fc"
            arcpy.MultipartToSinglepart_management(merged_fc, singlepart_fc)
            messages.addMessage("Multipart to single part conversion completed.")

            # Add a field if it doesn't already exist
            messages.addMessage("Adding and calculating a field for tree width...")
            width_field = "Width"
            if not arcpy.ListFields(singlepart_fc, width_field):
                arcpy.AddField_management(singlepart_fc, width_field, "DOUBLE")
            with arcpy.da.UpdateCursor(singlepart_fc, ["SHAPE@", width_field]) as cursor:
                for row in cursor:
                    polygon = row[0]  # Geometry object
                    extent = polygon.extent  # Get the extent (bounding box)
                    width = extent.width  # Width of the bounding box
                    row[1] = width / 2  # Assign the width to the field
                    cursor.updateRow(row)

            del cursor  # Clean up cursor object

            messages.addMessage("Field for tree width added and calculated.")
           

            # Feature to point
            messages.addMessage("Converting features to points...")
            points_fc = "in_memory/points_fc"
            arcpy.management.FeatureToPoint(singlepart_fc, points_fc, "INSIDE")
            messages.addMessage("Features converted to points.")

            # Pairwise buffer
            messages.addMessage("Applying pairwise buffer...")
            buffer_fc_1 = "in_memory/buffer_fc_1"
            arcpy.analysis.PairwiseBuffer(points_fc, buffer_fc_1, "Width", "NONE")
            messages.addMessage("Pairwise buffer applied.")

            # Delete all fields from the output buffer except the geometry field
            messages.addMessage("Deleting all fields from the output buffer except the geometry field...")
            fields = arcpy.ListFields(buffer_fc_1)
            
            drop_fields = [field.name for field in fields if field.type not in ('OID', 'Geometry') and field.name != 'Shape_Area' and field.name != 'Shape_Length' and field.name != field_name]      
            if drop_fields:
                arcpy.management.DeleteField(buffer_fc_1, drop_fields)
            messages.addMessage("Fields deleted.")


            # Remove small polygons
            messages.addMessage("Removing polygons with area less than 0.25 square meters...")
            with arcpy.da.UpdateCursor(buffer_fc_1, ["SHAPE@", "SHAPE@AREA"]) as cursor:
                for row in cursor:
                    if row[1] < 0.25:
                        cursor.deleteRow()
            del cursor  # Clean up cursor object
            messages.addMessage("Small polygons removed.")

            # Delete any fields that aren't in polygon_fc fields
            messages.addMessage("Deleting fields that aren't in buffer_fc fields...")
            buffer_fc_fields = [field.name for field in arcpy.ListFields(buffer_fc)]
            output_fields = [field.name for field in arcpy.ListFields(buffer_fc_1)]
            fields_to_delete = [field for field in output_fields if field not in buffer_fc_fields and field not in ('OID', 'Geometry', 'Shape_Length', 'Shape_Area', field_name)]
           
            with arcpy.da.UpdateCursor(buffer_fc_1, ["class"]) as cursor:
                for row in cursor:
                    row[0] = unique_value
                    cursor.updateRow(row)
            if fields_to_delete:
                arcpy.management.DeleteField(buffer_fc_1, fields_to_delete)
            else:
                messages.addMessage("No fields to delete.")
            messages.addMessage("Fields that aren't in polygon_fc fields deleted.")

            if first_iteration:
                arcpy.management.CopyFeatures(buffer_fc_1, final_output_fc)
                first_iteration = False
            else:
                # Perform spatial join with final output feature class
                messages.addMessage("Performing spatial join with final output feature class...")
                temp_spatial_join_fc = "in_memory/temp_spatial_join_fc"
                arcpy.analysis.SpatialJoin(
                    target_features=buffer_fc_1,
                    join_features=final_output_fc,
                    out_feature_class=temp_spatial_join_fc,
                    join_operation="JOIN_ONE_TO_ONE",
                    join_type="KEEP_ALL",
                    match_option="INTERSECT",
                    search_radius=None,
                    distance_field_name="",
                    match_fields=None
                )
                messages.addMessage("Spatial join with final output feature class completed.")

                # Delete attributes with Join_Count not None
                messages.addMessage("Deleting attributes with Join_Count not None...")
                with arcpy.da.SearchCursor(temp_spatial_join_fc, ["Join_Count", "SHAPE@"]) as search_cursor:
                    with arcpy.da.InsertCursor(final_output_fc, ["SHAPE@"]) as insert_cursor:
                        for row in search_cursor:
                            if row[0] == 0:
                                insert_cursor.insertRow([row[1]])
                messages.addMessage("Attributes with Join_Count None inserted into the final output feature class.")

            # Delete intermediate layers
            messages.addMessage("Deleting intermediate layers...")
            arcpy.management.Delete([polygon_fc, buffer_fc, tree_area_fc_1, tree_area_fc_2, mbg_fc, tessellation_fc, intersect_fc, merged_fc, singlepart_fc, points_fc, buffer_fc_1])
            messages.addMessage("Intermediate layers deleted.")

        # Copy final output to the specified output feature class
        arcpy.management.CopyFeatures(final_output_fc, output_feature_class)

        messages.addMessage("Final output copied to the specified output feature class.")

        messages.addMessage("Post-processing workflow completed successfully.")

        return

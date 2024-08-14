import arcpy
import os


class Toolbox(object):
    def __init__(self):
        """Define the toolbox (the name of the toolbox is the name of the
        .pyt file)."""
        self.label = "WHOToolbox"
        self.alias = "WHO Toolbox"

        # List of tool classes associated with this toolbox
        self.tools = [fromWKT]


class fromWKT(object):
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "FromWKT"
        self.description = "Tool to import wkt points from csv"
        self.canRunInBackground = True

    def getParameterInfo(self):
        """Define parameter definitions"""
        param_csv = arcpy.Parameter(
            name="param_csv",
            displayName="WKT CSV Input",
            direction="Input",
            datatype="DETable",
            parameterType="Required",
            symbology=".csv")

        param_output_fc = arcpy.Parameter(
            name="param_output_fc",
            displayName="Output Feature Class",
            direction="Output",
            datatype="DEFeatureClass",
            parameterType="Required")
        
        param_wkt_field = arcpy.Parameter(
            name="param_wkt_field",
            displayName="WKT Field Name",
            direction="Input",
            datatype="Field",
            parameterType="Required") 
        param_wkt_field.parameterDependencies = [param_csv.name]
        return  [param_csv, param_output_fc, param_wkt_field]
    def isLicensed(self):
        """Set whether tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal
        validation is performed.  This method is called whenever a parameter
        has been changed."""
        if parameters[0].altered:
            valid_fieldtypes = ['Integer', 'SmallInteger', 'Double', 'Single']
            fields = [f for f in arcpy.Describe(parameters[0]).fields
                      if f.type in valid_fieldtypes]
            parameters[2] = fields

        return 

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter.  This method is called after internal validation."""
        return

    def execute(self, parameters, messages):
        """The source code of the tool."""

        csv = parameters[0].valueAsText
        output_fc_fullpath = parameters[1].valueAsText
        wkt_field = parameters[2].valueAsText

        output_gdb = os.path.dirname(output_fc_fullpath)
        output_fc = output_fc_fullpath.split("\\")[-1]
        old_field_names = []
        field_names = []

        for field in arcpy.ListFields(csv):
            old_field_names.append(field.name)
            if " " in field.name:
                field.name = field.name.replace(" ", "_")
            elif "." in field.name:
                field.name = field.name.replace(".", "_")
            elif "-" in field.name:
                field.name = field.name.replace("-", "_")
            field_names.append(field.name)
        wkt_field_Index = field_names.index(wkt_field)

        cursor =arcpy.da.SearchCursor(csv, old_field_names)
        data_to_append = []
        for row in cursor:
            sr = row[wkt_field_Index]
            sr = sr.split(";")[0].split("=")[-1]
            sr = int(sr)
            row = list(row)
            data_to_append.append(row)
        del cursor

        arcpy.AddMessage(f"{len(data_to_append)} features to append")
        arcpy.AddMessage(f" Creating {output_fc} feature class")
        
        arcpy.CreateFeatureclass_management(out_path=output_gdb, out_name=output_fc, geometry_type="POINT", template=csv,has_z="ENABLED", spatial_reference=sr)
        
        arcpy.AddMessage(f" Created {output_fc} feature class")
        
        cursor = arcpy.da.InsertCursor(output_fc_fullpath, field_names + ["SHAPE@X", "SHAPE@Y", "SHAPE@Z"])
        for row in data_to_append:
            wkt = row[wkt_field_Index].split(";")[-1].split(" ")[1:]
            x = float(wkt[0].split("(")[-1])
            y = float(wkt[1])
            z = float(wkt[2].split(")")[0])
            outRow = row + [x, y, z]
            cursor.insertRow(outRow)
        del cursor
        
        arcpy.AddMessage(f"Added {len(data_to_append)} to {output_fc} feature class")
                        


        
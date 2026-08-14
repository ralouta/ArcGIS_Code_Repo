import arcpy


def string_parameter(display_name, name, category, value, choices, required=False):
    parameter = arcpy.Parameter(
        displayName=display_name,
        name=name,
        datatype="GPString",
        parameterType="Required" if required else "Optional",
        direction="Input",
    )
    parameter.filter.type = "ValueList"
    parameter.filter.list = list(choices)
    parameter.value = value
    parameter.category = category
    return parameter


def feature_parameter(display_name, name, category, geometry_types):
    parameter = arcpy.Parameter(
        displayName=display_name,
        name=name,
        datatype="GPFeatureLayer",
        parameterType="Optional",
        direction="Input",
    )
    parameter.filter.list = geometry_types
    parameter.category = category
    return parameter


def numeric_parameter(display_name, name, datatype, category, value=None):
    parameter = arcpy.Parameter(
        displayName=display_name,
        name=name,
        datatype=datatype,
        parameterType="Optional",
        direction="Input",
    )
    parameter.value = value
    parameter.category = category
    return parameter
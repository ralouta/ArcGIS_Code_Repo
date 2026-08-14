import os
import re

import arcpy


def usable_field_names(feature_class):
    if not feature_class:
        return []
    try:
        return [
            field.name
            for field in arcpy.ListFields(feature_class)
            if field.type not in ("OID", "Geometry", "Blob", "Raster")
        ]
    except Exception:
        return []


def validate_minimum_example_count(sample_points, parameter):
    try:
        count = int(arcpy.management.GetCount(sample_points)[0])
    except Exception:
        return
    if count < 6:
        parameter.setErrorMessage(
            f"Provide at least 6 example point features; the selected layer contains {count}."
        )


def validate_example_class_field(sample_points, class_field, parameter):
    if not sample_points:
        return
    if not class_field:
        parameter.setErrorMessage(
            "Choose the field that contains the user-defined example classes."
        )
        return
    if class_field not in usable_field_names(sample_points):
        parameter.setErrorMessage("Choose a valid non-system field from the example points.")
        return
    try:
        class_counts = {}
        with arcpy.da.SearchCursor(sample_points, [class_field]) as cursor:
            for (value,) in cursor:
                label = str(value).strip() if value is not None else ""
                if label:
                    class_counts[label] = class_counts.get(label, 0) + 1
        if not class_counts:
            parameter.setErrorMessage("The selected class field has no populated values.")
        elif min(class_counts.values()) < 6:
            insufficient = ", ".join(
                f"{label} ({count})" for label, count in class_counts.items() if count < 6
            )
            parameter.setErrorMessage(
                "Each class needs at least 6 example points. Insufficient classes: "
                f"{insufficient}."
            )
    except Exception:
        pass


def geodatabase_workspace(dataset_path):
    match = re.search(r"(?i)^(.+?\.(?:gdb|sde))(?:[\\/].*)?$", dataset_path or "")
    return match.group(1) if match else None


def same_dataset(first_dataset, second_dataset):
    if not first_dataset or not second_dataset:
        return False

    normalized_paths = []
    for dataset in (first_dataset, second_dataset):
        try:
            dataset = arcpy.Describe(dataset).catalogPath
        except Exception:
            pass
        normalized_paths.append(os.path.normcase(os.path.normpath(str(dataset))))
    return normalized_paths[0] == normalized_paths[1]


def meters_to_spatial_units(distance_meters, spatial_reference):
    if not spatial_reference or spatial_reference.type != "Projected":
        raise arcpy.ExecuteError(
            "Target features and the area of interest must use a projected coordinate "
            "system so meter-based cell sizes and footprint tolerances are meaningful."
        )
    meters_per_unit = spatial_reference.metersPerUnit
    if not meters_per_unit or meters_per_unit <= 0:
        raise arcpy.ExecuteError(
            "The target coordinate system does not define a valid linear unit."
        )
    return distance_meters / meters_per_unit


def square_meters_to_spatial_units(area_square_meters, spatial_reference):
    return meters_to_spatial_units(1.0, spatial_reference) ** 2 * area_square_meters


def validate_coverage_parameters(moderate_parameter, high_parameter):
    moderate_threshold = (
        float(moderate_parameter.value) if moderate_parameter.value is not None else None
    )
    high_threshold = float(high_parameter.value) if high_parameter.value is not None else None
    if moderate_threshold is not None and not 0 < moderate_threshold < 100:
        moderate_parameter.setErrorMessage(
            "Moderate coverage must be greater than 0 and less than 100."
        )
    if high_threshold is not None and not 0 < high_threshold <= 100:
        high_parameter.setErrorMessage(
            "High coverage must be greater than 0 and at most 100."
        )
    if (
        moderate_threshold is not None
        and high_threshold is not None
        and moderate_threshold >= high_threshold
    ):
        high_parameter.setErrorMessage("High coverage must be greater than moderate coverage.")
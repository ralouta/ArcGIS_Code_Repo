"""Remove ship-detection polygons with implausible oriented aspect ratios.

Use as an ArcGIS Pro script tool with these parameters:
0. Input Ship Detection Polygons (Feature Layer)
1. Output Feature Class (Feature Class)
2. Maximum Length-to-Width Ratio (Double, optional; default 30)
"""

import arcpy
import os
import uuid


DEFAULT_MAX_ASPECT_RATIO = 30.0


def clean_ship_detection_polygons(in_features, out_features, max_aspect_ratio):
    """Copies polygons to an output feature class and removes extreme aspect ratios."""
    if max_aspect_ratio <= 1:
        raise ValueError("Maximum Length-to-Width Ratio must be greater than 1.")

    arcpy.management.CopyFeatures(in_features, out_features)
    output_description = arcpy.Describe(out_features)
    output_oid_field = output_description.OIDFieldName
    scratch_mbr = os.path.join(
        arcpy.env.scratchGDB,
        "ship_detection_mbr_{}".format(uuid.uuid4().hex),
    )

    try:
        arcpy.management.MinimumBoundingGeometry(
            out_features,
            scratch_mbr,
            "RECTANGLE_BY_WIDTH",
            "NONE",
            "",
            "MBG_FIELDS",
        )

        invalid_feature_ids = []
        with arcpy.da.SearchCursor(
            scratch_mbr, ["ORIG_FID", "MBG_Width", "MBG_Length"]
        ) as cursor:
            for original_id, width, length in cursor:
                if not width or not length:
                    # A zero-dimension polygon cannot represent a ship footprint.
                    invalid_feature_ids.append(original_id)
                    continue
                aspect_ratio = max(width, length) / min(width, length)
                if aspect_ratio > max_aspect_ratio:
                    invalid_feature_ids.append(original_id)

        if invalid_feature_ids:
            invalid_feature_ids = set(invalid_feature_ids)
            with arcpy.da.UpdateCursor(out_features, [output_oid_field]) as cursor:
                for row in cursor:
                    if row[0] in invalid_feature_ids:
                        cursor.deleteRow()

        kept_count = int(arcpy.management.GetCount(out_features)[0])
        removed_count = len(invalid_feature_ids)
        arcpy.AddMessage(
            "Removed {} polygon(s) with a length-to-width ratio above {}. "
            "Kept {} polygon(s).".format(
                removed_count, max_aspect_ratio, kept_count
            )
        )
    finally:
        if arcpy.Exists(scratch_mbr):
            arcpy.management.Delete(scratch_mbr)


def main():
    in_features = arcpy.GetParameterAsText(0)
    out_features = arcpy.GetParameterAsText(1)
    max_aspect_ratio_text = arcpy.GetParameterAsText(2)
    max_aspect_ratio = float(max_aspect_ratio_text or DEFAULT_MAX_ASPECT_RATIO)

    clean_ship_detection_polygons(in_features, out_features, max_aspect_ratio)
    arcpy.SetParameterAsText(1, out_features)


if __name__ == "__main__":
    main()

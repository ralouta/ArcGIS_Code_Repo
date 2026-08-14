import gc
import hashlib
import json
import os

import arcpy


def generate_embeddings_with_model(**kwargs):
    generate_embeddings = getattr(
        getattr(arcpy, "geoai", None), "GenerateEmbeddingsUsingAIModels", None
    )
    if not generate_embeddings:
        raise arcpy.ExecuteError(
            "Generate Embeddings Using AI Models is unavailable in this ArcGIS Pro "
            "installation. Install or update the GeoAI deep-learning tools required "
            "by the ArcGIS Pro GeoAI toolbox."
        )
    return generate_embeddings(**kwargs)


def merge_embedding_chunks(chunk_outputs, output_embeddings, valid_embedding_output):
    arcpy.management.Merge(
        inputs=";".join(chunk_outputs),
        output=output_embeddings,
        field_mappings=None,
        add_source="NO_SOURCE_INFO",
        field_match_mode="AUTOMATIC",
    )
    if not valid_embedding_output(output_embeddings):
        raise arcpy.ExecuteError(
            "The direct embedding merge did not create a valid feature class."
        )


def embedding_checkpoint_workspace(
    cache_root,
    model,
    grid_size,
    batch_size,
    output_spatial_reference,
    embedding_chunk_pixels,
):
    model_size = os.path.getsize(model) if os.path.isfile(model) else None
    wkid = (
        getattr(output_spatial_reference, "factoryCode", 0)
        or getattr(output_spatial_reference, "latestWkid", 0)
        or output_spatial_reference.name
    )
    checkpoint_properties = {
        "model": os.path.abspath(model).lower(),
        "model_size": model_size,
        "grid_size": int(grid_size),
        "output_wkid": wkid,
        "chunk_pixels": embedding_chunk_pixels,
        "input_strategy": "per_chunk_raster_v1",
    }
    checkpoint_workspace = hashed_embedding_workspace(cache_root, checkpoint_properties)
    if arcpy.Exists(checkpoint_workspace):
        return checkpoint_workspace

    legacy_batch_sizes = [int(batch_size)] + [
        value for value in range(1, 129) if value != int(batch_size)
    ]
    for legacy_batch_size in legacy_batch_sizes:
        legacy_properties = dict(checkpoint_properties)
        legacy_properties["batch_size"] = legacy_batch_size
        legacy_workspace = hashed_embedding_workspace(cache_root, legacy_properties)
        if arcpy.Exists(legacy_workspace):
            return legacy_workspace
    return checkpoint_workspace


def hashed_embedding_workspace(cache_root, checkpoint_properties):
    checkpoint_key = json.dumps(checkpoint_properties, sort_keys=True)
    checkpoint_id = hashlib.sha256(checkpoint_key.encode("utf-8")).hexdigest()[:12]
    return os.path.join(cache_root, f"embeddings_{checkpoint_id}.gdb")


def release_gpu_memory():
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:
        pass
    try:
        arcpy.management.ClearWorkspaceCache()
    except Exception:
        pass


def has_embedding_field(feature_class):
    if not arcpy.Exists(feature_class):
        return False
    try:
        return any(field.type.upper() == "BLOB" for field in arcpy.ListFields(feature_class))
    except Exception:
        return False


def valid_embedding_output(feature_class):
    if not has_embedding_field(feature_class):
        return False
    try:
        return int(arcpy.management.GetCount(feature_class)[0]) > 0
    except Exception:
        return False
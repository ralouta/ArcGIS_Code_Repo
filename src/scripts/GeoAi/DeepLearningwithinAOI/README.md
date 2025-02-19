# Deep Learning with Boundaries - Documentation

Welcome to the documentation for the Deep Learning with Boundaries tools. This guide will walk you through the setup, usage, and output of the tools, providing code snippets and placeholders for relevant screenshots.

## Toolbox Overview

The toolbox contains two main tools:
- Classify Pixels Using Deep Learning
- Detect Objects Using Deep Learning

## Classify Pixels Using Deep Learning

This tool classifies pixels using deep learning with additional processing geometry parameters.

### Parameters

- **Input Raster:** The raster dataset to be classified.
- **Model Definition:** The deep learning model definition file (.emd).
- **Output Classified Raster:** The output classified raster dataset.
- **Processing Geometry:** The geometry to be used for processing.
- **Arguments:** Additional arguments for the deep learning model.
- **Tessellation Size (Square Kilometers):** The size of the tessellation area in square kilometers.

### Workflow Explanation

The workflow for the Classify Pixels Using Deep Learning tool involves several key steps:
1. **Define the Area of Interest (AOI):** The user specifies the AOI using the processing geometry parameter. This ensures that only the relevant areas are processed, avoiding unnecessary computation on areas outside the AOI.
2. **Generate Tessellation Grid:** Based on the user-defined tessellation size and model arguments (batch size and tile size), the tool generates a tessellation grid that divides the AOI into smaller, manageable extents.
3. **Clip with AOI:** The tessellation grid is clipped with the AOI to ensure that only the grid cells overlapping the AOI are processed.
4. **Classify Pixels:** For each extent in the tessellation grid, the tool classifies the pixels using the deep learning model. The results are saved as individual raster datasets.
5. **Merge Results:** The individual raster datasets are merged into a single output classified raster.

### Intermediate Outputs

During the workflow, several intermediate outputs are generated:
- **Tessellation Grid:** The grid that divides the AOI into smaller extents.
- **Clipped Grid:** The tessellation grid after being clipped with the AOI.
- **Classified Raster Datasets:** The individual raster datasets with classified pixels for each extent.

### Code Snippet

```python
class ClassifyPixelsUsingDeepLearning(object):
    def __init__(self):
        self.label = "Classify Pixels Using Deep Learning"
        self.description = "Classify pixels using deep learning with additional processing geometry parameter."
        self.canRunInBackground = False
        self.error_message = None

    def getParameterInfo(self):
        params = []
        # Define parameters here
        return params

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        self.error_message = None
        # Update parameters here
        return

    def updateMessages(self, parameters):
        if self.error_message:
            parameters[1].setErrorMessage(self.error_message)
        return

    def execute(self, parameters, messages):
        # Define the AOI
        aoi = parameters[0].valueAsText
        # Generate tessellation grid
        tessellation_grid = generate_tessellation_grid(aoi, parameters)
        # Clip with AOI
        clipped_grid = clip_with_aoi(tessellation_grid, aoi)
        # Classify pixels
        classified_rasters = classify_pixels(clipped_grid, parameters)
        # Merge results
        merged_results = merge_classified_rasters(classified_rasters)
        return merged_results
```

## Detect Objects Using Deep Learning

This tool detects objects using deep learning with additional processing geometry parameters.

### Parameters

- **Input Raster:** The raster dataset to be processed.
- **Model Definition:** The deep learning model definition file (.emd).
- **Output Detected Objects:** The output feature class with detected objects.
- **Processing Geometry:** The geometry to be used for processing.
- **Arguments:** Additional arguments for the deep learning model.
- **Run Non-Maximum Suppression (NMS):** Whether to run NMS.
- **Confidence Score Field:** The field for confidence scores.
- **Class Value Field:** The field for class values.
- **Max Overlap Ratio:** The maximum overlap ratio for NMS.
- **Use Pixel Space:** Whether to use pixel space.
- **Tessellation Size (Square Kilometers):** The size of the tessellation area in square kilometers.

### Workflow Explanation

The workflow for the Detect Objects Using Deep Learning tool involves several key steps:
1. **Define the Area of Interest (AOI):** The user specifies the AOI using the processing geometry parameter. This ensures that only the relevant areas are processed, avoiding unnecessary computation on areas outside the AOI.
2. **Generate Tessellation Grid:** Based on the user-defined tessellation size and model arguments (batch size and tile size), the tool generates a tessellation grid that divides the AOI into smaller, manageable extents.
3. **Clip with AOI:** The tessellation grid is clipped with the AOI to ensure that only the grid cells overlapping the AOI are processed.
4. **Detect Objects:** For each extent in the tessellation grid, the tool detects objects using the deep learning model. The results are saved as individual feature classes.
5. **Merge Results:** The individual feature classes are merged into a single output feature class with detected objects.

### Intermediate Outputs

During the workflow, several intermediate outputs are generated:
- **Tessellation Grid:** The grid that divides the AOI into smaller extents.
- **Clipped Grid:** The tessellation grid after being clipped with the AOI.
- **Detected Objects Feature Classes:** The individual feature classes with detected objects for each extent.

### Code Snippet

```python
class DetectObjectsUsingDeepLearning(object):
    def __init__(self):
        self.label = "Detect Objects Using Deep Learning"
        self.description = "Detect objects using deep learning with additional processing geometry parameter."
        self.canRunInBackground = False
        self.error_message = None

    def getParameterInfo(self):
        params = []
        # Define parameters here
        return params

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        self.error_message = None
        # Update parameters here
        return

    def updateMessages(self,
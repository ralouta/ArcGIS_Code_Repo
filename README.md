# ArcGIS Code Repo

This repository contains Python scripts and Jupyter notebooks for managing and analyzing geospatial data with ArcGIS Pro and the ArcGIS Deep Learning Framework.

## Prerequisites

- ArcGIS Pro
- ArcGIS Deep Learning Framework - Download the installers from the [Esri deep-learning-frameworks GitHub repository](https://github.com/Esri/deep-learning-frameworks).

## Installation

Please ensure you have the prerequisites installed before proceeding.

## Directory Structure

- `data/`: Contains input and output data.
- `docs/`: Contains documentation and images.
- `src/`: Contains the source code for the project.
    - `scripts/`: Contains Python scripts and ArcGIS Pro toolboxes (.pyt files).
    - `tests/`: Contains Jupyter notebooks for testing the scripts and toolboxes.
- `README.md`: This file.
- `requirements.txt`: Lists the Python packages required to run the scripts and notebooks.

## Using .pyt file in ArcGIS Pro

1. **Open ArcGIS Pro**: Start ArcGIS Pro and open a new or existing project.
2. **Add Toolbox**: In the Catalog pane, right-click on Toolboxes. Then click on Add Toolbox.
3. **Navigate to .pyt file**: In the Add Toolbox window, navigate to the location of your `.pyt` file. This file is located in the `src > scripts` directory of your project. Select the file and click Open.
4. **Access the Tool**: The toolbox should now be visible in the Catalog pane under Toolboxes. Expand the toolbox to see the list of tools available. Double-click on a tool to open it.
5. **Run the Tool**: Fill in the required parameters for the tool and click Run to execute it.

Remember to save your project to keep the toolbox in your project for future use.

## Scripts and Toolboxes

- `CreateSentinelMosaicfromAOI.ipynb`: A Jupyter notebook for creating a Sentinel mosaic from an Area of Interest (AOI).
- `MultiResolutionDL.pyt`: An ArcGIS Pro toolbox for multi-scale deep learning. The toolbox contains a single tool, also named MultiScaleDL, which performs object detection on geospatial raster data using a deep learning model.

## Tests

The `tests/` directory contains Jupyter notebooks for testing the scripts and toolboxes. For example, `CreateTerrainMosaicfromAOI.ipynb` tests the creation of a terrain mosaic from an AOI.
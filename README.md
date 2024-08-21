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
    - `scripts/`: Contains Python scripts and ArcGIS Pro toolboxes (.pyt files). These scripts and toolboxes are used for various geospatial data management and analysis tasks, such as creating and manipulating geodatabases, managing ArcGIS Online resources, and performing deep learning on geospatial data.
        - `AGOL Management/`: Scripts for managing ArcGIS Online resources.
            - `changeAllGroupsOwnedByUser.ipynb`: Changes ownership of all groups owned by a specific user.
            - `DeleteUsersandItemsfromDate.ipynb`: Deletes users and items based on a specified date.
            - `DeleteUsersandItemsfromList.ipynb`: Deletes users and items from a provided list.
            - `GetArcGISInActiveCreators.ipynb`: Retrieves a list of inactive ArcGIS creators.
            - `GetArcGISProInActiveUSers.ipynb`: Retrieves a list of inactive ArcGIS Pro users.
            - `getManageUserItemsGroupsItems.ipynb`: Manages user items and groups in ArcGIS Online.
        - `Feature Service Management/`: Scripts for managing feature services.
        - `General purpose code/`: General purpose scripts for various tasks.
        - `GeoAi/`: Scripts for geospatial AI tasks.
        - `Imagery notebooks/`: Notebooks for managing and analyzing imagery data.
    - `tests/`: Contains Jupyter notebooks for testing the scripts and toolboxes.
        - `Demo-Geospatialcenter.ipynb`: Demonstrates geospatial data processing.
        - `dynamic_arguments.ipynb`: Tests dynamic argument handling in scripts.
        - `maxgumby_data.ipynb`: Tests data processing for the MaxGumby dataset.
        - `trips_pages_200.csv`: Sample data for testing.

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

The scripts and toolboxes in the `src/scripts/` directory are designed to work with ArcGIS Pro and the ArcGIS Deep Learning Framework. They provide functionality for managing and analyzing geospatial data, including creating and manipulating geodatabases, managing ArcGIS Online resources, and performing deep learning on geospatial data. Each script or toolbox is documented with comments explaining its purpose and usage.
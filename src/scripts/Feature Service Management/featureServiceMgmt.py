from arcgis.gis import GIS
import getpass
import ipywidgets as widgets
from IPython.display import display
import pandas as pd

class FeatureServiceDataAnalyzer:
    def __init__(self):
        self.gis = None
        self.item = None
        self.feature_layer = None


    
    def authenticate_and_get_item(self):
        """
        Authenticate with AGOL and get the item.
        """
        # Prompt user for AGOL organization URL
        org_url = input("Enter your AGOL organization URL (e.g., https://myorg.maps.arcgis.com): ")

        # Prompt user to choose authentication method
        auth_method = input("Choose authentication method (1 for Username/Password, 2 for Client ID): ")

        if auth_method == '1':
            # Prompt user for AGOL credentials
            username = input("Enter your AGOL username: ")
            password = getpass.getpass("Enter your AGOL password: ")
            
            # Connect to AGOL using username and password
            self.gis = GIS(org_url, username, password)
        elif auth_method == '2':
            # Prompt user for client ID
            client_id = input("Enter your client ID: ")
            self.gis = GIS(org_url, client_id=client_id)
        else:
            print("Invalid authentication method selected.")
            return

        # Provide the AGOL item ID
        item_id = input("Enter the AGOL item ID: ")

        # Get the item
        self.item = self.gis.content.get(item_id)

    def display_layer_dropdown(self):
        """
        Display a dropdown widget for selecting the layer.
        """
        if not self.item:
            raise ValueError("No item found. Please authenticate and get the item first.")
        
        # Create a dropdown widget for selecting the layer
        layer_options = [(layer.properties.name, i) for i, layer in enumerate(self.item.layers)]
        
        if len(layer_options) == 1:
            # If there is only one layer, select it automatically
            self.feature_layer = self.item.layers[0]
            print(f"Automatically selected layer: {self.feature_layer.properties.name}")
        else:
            layer_dropdown = widgets.Dropdown(
                options=layer_options,
                description='Select Layer:',
                disabled=False,
            )

            def on_layer_change(change):
                self.feature_layer = self.item.layers[change['new']]
                print(f"Selected layer: {self.feature_layer.properties.name}")

            layer_dropdown.observe(on_layer_change, names='value')

            # Display the dropdown widget
            display(layer_dropdown)

    def query_feature_layer_to_df(self):
        """
        Query the selected feature layer and return its data as a DataFrame.
        """
        if not self.feature_layer:
            raise ValueError("No feature layer selected. Please select a layer using the dropdown first.")
        
        # Query the feature layer
        features = self.feature_layer.query(where="1=1", out_fields="*").features
        
        # Convert the features to a DataFrame
        data = [feature.attributes for feature in features]
        df = pd.DataFrame(data)
        
        return df
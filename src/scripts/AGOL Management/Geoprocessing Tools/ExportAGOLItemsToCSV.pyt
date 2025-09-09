import arcpy
import csv
from arcgis.gis import GIS
from datetime import datetime

class ExportAGOLItemsToCSV(object):
    def __init__(self):
        self.label = "Export ArcGIS Online Items to CSV"
        self.description = "Exports all Web AppBuilder items in the organization to a CSV file."
        self.canRunInBackground = True

    def getParameterInfo(self):
        params = []
        output_csv = arcpy.Parameter(
            displayName="Output CSV File",
            name="output_csv",
            datatype="DEFile",
            parameterType="Required",
            direction="Output"
        )
        output_csv.filter.list = ["csv"]
        output_csv.displayName = "Output CSV File (e.g. C:/path/to/output.csv)"
        output_csv.value = None
        params.append(output_csv)
        return params

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        output_csv = parameters[0].valueAsText
        try:
            messages.addMessage("Connecting to ArcGIS Online using active Pro session...")
            gis = GIS("pro")
            messages.addMessage("Searching for Web AppBuilder items (max 10,000)...")
            items = gis.content.search(query="type:Web AppBuilder", max_items=10000)
            messages.addMessage(f"Found {len(items)} items. Exporting to CSV...")
            with open(output_csv, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["itemid", "title", "owner", "owner_email", "type", "url", "last_update", "num_views"])
                for item in items:
                    try:
                        owner = item.owner
                        owner_user = gis.users.get(owner)
                        owner_email = owner_user.email if owner_user else ""
                        last_update = datetime.fromtimestamp(item.modified/1000).strftime('%Y-%m-%d %H:%M:%S') if item.modified else ""
                        writer.writerow([
                            item.id,
                            item.title,
                            owner,
                            owner_email,
                            item.type,
                            item.url,
                            last_update,
                            item.numViews
                        ])
                    except Exception as item_err:
                        messages.addWarningMessage(f"Error processing item {getattr(item, 'id', '')}: {item_err}")
            messages.addMessage(f"Export complete. CSV saved to: {output_csv}")
        except Exception as e:
            messages.addErrorMessage(f"Failed to export items: {e}")
            raise

class Toolbox(object):
    def __init__(self):
        self.label = "AGOL Export Tools"
        self.alias = "agolexporttools"
        self.tools = [ExportAGOLItemsToCSV]

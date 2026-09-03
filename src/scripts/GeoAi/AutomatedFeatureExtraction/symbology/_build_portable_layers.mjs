import { writeFileSync } from "node:fs";
import { join } from "node:path";

const styles = {
  Buildings: [[194, 162, 120, 65], [99, 77, 52, 100], 0.8],
  Bridges: [[171, 139, 103, 60], [85, 65, 45, 100], 1.2],
  Roads: [[216, 210, 196, 55], [137, 133, 123, 100], 0.7],
  Water_Bodies: [[95, 166, 214, 55], [42, 111, 158, 100], 0.8],
  Rail_Corridors: [[105, 97, 88, 45], [59, 54, 49, 100], 1.0],
  Impervious_Surfaces: [[190, 187, 177, 50], [126, 124, 117, 100], 0.6],
  Parking_Areas: [[180, 178, 169, 45], [112, 111, 104, 100], 0.6],
  Solar_Arrays: [[75, 105, 130, 55], [34, 61, 85, 100], 0.7],
  Sports_Surfaces: [[151, 188, 105, 50], [72, 124, 65, 100], 0.8],
  Swimming_Pools: [[52, 157, 214, 65], [19, 103, 157, 100], 0.8],
  Construction_Areas: [[203, 145, 62, 45], [143, 91, 30, 100], 0.8],
  Material_Stockpiles: [[183, 132, 78, 50], [122, 78, 38, 100], 0.8],
  Bare_Ground: [[216, 195, 148, 45], [158, 133, 84, 100], 0.7],
  Flooded_Areas: [[79, 146, 201, 40], [31, 95, 150, 100], 0.8],
  Debris: [[153, 96, 81, 45], [104, 53, 43, 100], 0.8],
  Vehicles: [[83, 88, 91, 60], [36, 40, 42, 100], 0.6],
  Trees: [[71, 139, 77, 45], [35, 98, 48, 100], 0.7],
  Forest_Cover: [[104, 153, 82, 35], [55, 105, 55, 100], 0.7],
  Agricultural_Fields: [[176, 190, 99, 35], [112, 132, 59, 100], 0.8],
  Park_Like_Green_Space: [[126, 173, 107, 35], [62, 118, 67, 100], 0.7],
  Utility_Poles: [[88, 95, 94, 45], [35, 42, 41, 100], 0.8],
  Other_Structures: [[163, 139, 113, 55], [96, 73, 51, 100], 0.8],
  Custom: [[160, 150, 160, 35], [97, 83, 97, 100], 0.8],
};

function layerDocument(name, fillColor, outlineColor, outlineWidth) {
  const layerPath = `CIMPATH=map/${name}.xml`;
  return {
    type: "CIMLayerDocument",
    version: "3.0.0",
    build: "3.0.0",
    layers: [layerPath],
    layerDefinitions: [{
      type: "CIMFeatureLayer",
      name,
      uRI: layerPath,
      useSourceMetadata: true,
      featureTable: {
        type: "CIMFeatureTable",
        displayField: "",
        dataConnection: {
          type: "CIMStandardDataConnection",
          workspaceConnectionString: "DATABASE=SymbologyTemplate.gdb",
          workspaceFactory: "FileGDB",
          dataset: "FeatureOutput",
          datasetType: "esriDTFeatureClass",
        },
      },
      selectable: true,
      showLabels: true,
      visibility: true,
      renderer: {
        type: "CIMSimpleRenderer",
        symbol: {
          type: "CIMSymbolReference",
          symbol: {
            type: "CIMPolygonSymbol",
            symbolLayers: [
              { type: "CIMSolidFill", enable: true, color: { type: "CIMRGBColor", values: fillColor } },
              { type: "CIMSolidStroke", enable: true, width: outlineWidth, color: { type: "CIMRGBColor", values: outlineColor } },
            ],
          },
        },
        patch: "Default",
        useRealWorldSymbolSizes: false,
      },
    }],
  };
}

for (const [name, [fillColor, outlineColor, outlineWidth]] of Object.entries(styles)) {
  writeFileSync(
    join(import.meta.dirname, `${name}.lyrx`),
    `${JSON.stringify(layerDocument(name, fillColor, outlineColor, outlineWidth), null, 2)}\n`,
  );
}
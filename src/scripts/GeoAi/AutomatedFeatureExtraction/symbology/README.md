# Topographic Symbology

Add `TopographicSymbology.pyt` to ArcGIS Pro, then run **Create Topographic Layer
Files** with any polygon feature layer and an output folder. It creates one portable
`.lyrx` file for every Automated Feature Extraction profile. The source layer is used
only to create a valid layer file; after adding a `.lyrx` to a map, use **Set Data
Source** to point it at the corresponding toolbox output.

The palette follows conventional topographic hierarchy: cool blue water, restrained
neutral transportation and built form, natural greens for vegetation, and warm earth
tones for change-review observations. Transparent fills keep imagery and contouring
readable; deliberate outlines retain legibility at operational mapping scales.

The output remains an automated candidate layer. Review and resolve `QC_STATUS` before
publishing features as authoritative topographic content.
# Production MEI files 

This repository contains the [MEI](https://music-encoding.org/) files generated (and manually reviewed) through the end-to-end [OMR workflow](http://ddmal.music.mcgill.ca/e2e-omr-documentation/) by [DDMAL](https://ddmal.music.mcgill.ca/).

The [MEI](https://music-encoding.org/) files are organized by manuscript. 
Each folder in the root of this repository represents a manuscript, denoted by its *siglum*. The files within the folder are organized by folio numbers of the manuscript.

Inside the folders, the naming convention for [MEI](https://music-encoding.org/) files is: ```<siglum>_<folio number>.mei```. 
For example, for the folio `001r` in the `cdn-hsmu-m2149l4` ([Salzinnes Antiphonal](https://cantus.uwaterloo.ca/source/123723)) manuscript, the [MEI](https://music-encoding.org/) filename is `cdn-hsmu-m2149l4_001r.mei`.

## Validation of the [MEI](https://music-encoding.org/) files

In addition to the files, this repository is configured to run some basic sanity checks on the MEI files. Currently, the implemented checks will:
- Verify that the files do not have any declared but unreferenced `<zone>` elements.

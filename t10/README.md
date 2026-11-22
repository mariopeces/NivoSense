# T1.0 evidence

- `counts.md`: labels per stratum and per date.
- `stratum_*.png`: chip montage per stratum (32 random points each, seed 1010, caption = id and label). Each point: true colour 340 m (x3), SWIR false colour B11/B8/B4 340 m (x3), true colour 1 km. The labelled 20 m pixel is inside the red marks.
- `pages/`: the 60 labelling pages exactly as labelled (shuffled order per date, captions show only the point id, no label or stratum); `page_ids.txt` lists the ids on each page in reading order (left to right, top to bottom). Usable for a blind relabel without rebuilding the L1C mosaics.
- `overviews/`: the 60 m L1C true-colour overviews with 500 m GLO-30 contours used to read each date's snowline before any point was drawn.
- `self_check/`: the labeller's own blind relabel of a 10% subset (seed 7, 175 points), done on fresh pages without the first labels: 137 of 137 decided pairs agree. This is not the G-Method check, only a consistency check.

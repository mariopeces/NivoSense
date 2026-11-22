run() { name="$1"; file="$2"; from="$3"; to="$4"
  rm -rf m && cp -r pr m && python - "$file" "$from" "$to" <<'PY'
import sys; p="m/"+sys.argv[1]; s=open(p).read(); assert sys.argv[2] in s, sys.argv[2]; open(p,"w").write(s.replace(sys.argv[2], sys.argv[3], 1))
PY
  res=$(cd m && python -m pytest tests/s2 -q -p no:cacheprovider --confcutdir=. --basetemp=$S/tmp/m -W ignore 2>&1 | tail -1)
  echo "$name => $res"; }
run "listing threshold 0.30->0.05" pipelines/s2/ingest.py "MIN_LISTED_VALID_FRACTION = 0.30" "MIN_LISTED_VALID_FRACTION = 0.05"
run "listed from coverage not valid" pipelines/s2/ingest.py "listed=bool(valid >= " "listed=bool(coverage >= "
run "one scale/offset for all tiles" pipelines/s2/mosaic.py "*scale_offset(item, asset)" "*scale_offset(acquisition.items[0], asset)"
run "group by date only (orbit ignored)" pipelines/s2/stac.py "granules[(day, orbit_of(item), tile_of(item))]" "granules[(day, 'R000', tile_of(item))]"
run "keep every baseline" pipelines/s2/stac.py "return [item for item in granules if _baseline(item) == newest]" "return granules"
run "keep only newest granule per tile" pipelines/s2/stac.py "return [item for item in granules if _baseline(item) == newest]" "return [max(granules, key=lambda i: i['properties']['s2:generation_time'])]"
run "complete always True" pipelines/s2/ingest.py "complete=not missing," "complete=True,"
run "no footprint filter" pipelines/s2/ingest.py "if domain.touches(item[\"geometry\"])" ""
run "SCL 2 (shadow) counted not valid" pipelines/s2/mosaic.py "SCL_NOT_VALID = (0, 1, 3, 8, 9, 10)" "SCL_NOT_VALID = (0, 1, 2, 3, 8, 9, 10)"
run "10m nodata block kept (nanmean)" pipelines/s2/mosaic.py ".mean(axis=(1, 3))" ".max(axis=(1, 3))"

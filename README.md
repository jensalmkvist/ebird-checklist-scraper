# ebird-checklist-scraper
This is a small web scraper for scraper ebird .csv checklists.

## Location coordinates

eBird's checklist CSV has no coordinates. Before each download the script
opens the checklist page, reads the location's latitude/longitude from it, and
appends `Latitude` and `Longitude` columns to the downloaded CSV.
[ebird-artportalen-importer](https://github.com/jensalmkvist/ebird-artportalen-importer)
uses these to suggest the nearest Artportalen sites.

If no coordinates are found the CSV is left as downloaded. Use `--no-coords`
to skip this step.

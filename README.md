# ebird-checklist-scraper
This is a small web scraper for scraper ebird .csv checklists.

## Credentials

The script logs in with `--username`/`--password`, or, if those are left out,
the `EBIRD_USERNAME` and `EBIRD_PASSWORD` environment variables. With no
password at all it asks for one.

```powershell
python ebird_month_download.py --year 2026 --month 10 --max 3
```

## Choosing checklists

Either a whole month, or a date range (the end defaults to today):

```powershell
python ebird_month_download.py --year 2026 --month 10
python ebird_month_download.py --start 2026-10-15 --end 2026-11-01
```

Dates are read from the "My checklists" page, so only checklists in the range
are opened. `--skip-ids FILE` skips the checklist IDs listed in the file (one
per line), e.g. ones already imported. The exit code is 3 if some checklists
failed to download (1 for other errors, 2 for bad arguments).

## Location coordinates

eBird's checklist CSV has no coordinates. Before each download the script
opens the checklist page, reads the location's latitude/longitude from it, and
appends `Latitude` and `Longitude` columns to the downloaded CSV.
[ebird-artportalen-importer](https://github.com/jensalmkvist/ebird-artportalen-importer)
uses these to suggest the nearest Artportalen sites.

If no coordinates are found the CSV is left as downloaded. Use `--no-coords`
to skip this step.

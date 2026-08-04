# ScrapMeme

Scrapes public meme templates from [imgflip.com/memetemplates](https://imgflip.com/memetemplates)
and, for each one, saves the **image** together with its **title** and **tags**.

Plain Node.js (tested on Node 24). Optional: **ffmpeg** on your PATH to convert
video templates into animated GIFs (see below).

## Usage

```bash
node scrape.js --pages 3
```

Options:

| Flag       | Default        | Meaning                                                     |
|------------|----------------|-------------------------------------------------------------|
| `--pages`  | `3`            | How many listing pages to scrape (40 memes per page).       |
| `--sort`   | `` (30 days)   | `top-all-time`, `top-new`, or empty for the 30-day ranking. |
| `--out`    | `output`       | Output directory.                                           |
| `--delay`  | `800`          | Delay in ms between requests (be polite to the server).     |
| `--refresh`| off            | Re-download and refresh memes already on disk.              |
| `--no-video` | off          | Skip video templates instead of converting them to gif.     |
| `--gif-width` | `400`       | Width (px) of gifs converted from video (height auto).      |
| `--gif-fps` | `12`          | Frame rate of converted gifs.                               |
| `--gif-seconds` | `6`       | Cap the duration of converted gifs (keeps them small).      |

Example — the 200 all-time most popular templates:

```bash
node scrape.js --pages 5 --sort top-all-time
```

## Re-running without duplicates

Runs are **incremental**. On startup the scraper loads every `meta/<Slug>.json`
already present, **skips** memes it already has (deduped by `slug`), downloads only
the new ones, and rebuilds `memes.json` / `memes.csv` from **old + new** combined.
Image files are named `<Slug>.<ext>`, so nothing is ever duplicated on disk.

To gather the most templates possible, just run it repeatedly with different
rankings — each run adds only what's missing:

```bash
node scrape.js --pages 500                      # 30-day ranking
node scrape.js --pages 500 --sort top-all-time  # all-time
node scrape.js --pages 500 --sort top-new       # newest
```

Pass `--refresh` to force re-downloading and updating tags for memes you already have.

## Output

```
output/
  images/<Slug>.jpg      the meme image (blank template)
  meta/<Slug>.json       that image's title + tags (sidecar)
  memes.json             combined manifest of every meme
  memes.csv              same data as a spreadsheet
```

Each `meta/<Slug>.json` looks like:

```json
{
  "title": "Bike Fall",
  "slug": "Bike-Fall",
  "tags": ["falling off bike", "stick in bike wheel", "bike blame", "..."],
  "image_file": "images/Bike-Fall.jpg",
  "image_url": "https://i.imgflip.com/69aty0.jpg",
  "page_url": "https://imgflip.com/meme/Bike-Fall"
}
```

## Video templates → GIF

Some templates are videos (only an `.mp4` exists, no static image). If **ffmpeg**
is on your PATH, the scraper downloads the mp4 and converts it to a compact
animated **gif** (two-pass palette, capped fps/width/duration) that the app can
play. Defaults aim for small files (~0.5–2 MB). Tune with `--gif-width`,
`--gif-fps`, `--gif-seconds`, or pass `--no-video` to skip these entirely. If
ffmpeg isn't found, video templates are skipped with a message.

## Notes

- Titles come from the template listing; tags come from each meme's page
  (its "aka:" alternate names plus page keywords).
- Only public template pages are fetched. A delay is added between requests.

#!/usr/bin/env node
/*
 * ScrapMeme — scrape public meme templates from imgflip.com/memetemplates
 *
 * For each meme it saves the image file plus its title and tags.
 *
 * Runs are incremental: it loads what is already in <out>/meta, skips memes it
 * already has (deduped by slug), and merges old + new into memes.json/csv. Re-run
 * it with different --sort / --pages to accumulate the most templates possible.
 * Pass --refresh to re-download and refresh memes already on disk.
 *
 * Video templates (no static image, only an .mp4) are converted to a compact
 * animated gif with ffmpeg (must be on PATH). Tune with --gif-width/--gif-fps/
 * --gif-seconds, or pass --no-video to skip them.
 *
 * Usage:
 *   node scrape.js [--pages N] [--sort top-all-time|top-new|] [--out DIR] [--delay MS]
 *                  [--refresh] [--no-video] [--gif-width N] [--gif-fps N] [--gif-seconds N]
 *
 * Examples:
 *   node scrape.js --pages 3
 *   node scrape.js --pages 200 --sort top-all-time   # then re-run with other sorts
 *   node scrape.js --pages 200 --sort top-new
 *
 * Output layout (default ./output):
 *   output/images/<Slug>.jpg      the meme image
 *   output/meta/<Slug>.json       sidecar: title + tags for that image
 *   output/memes.json             combined manifest of every meme
 *   output/memes.csv              same data as a spreadsheet
 */

const https = require("https");
const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

// ---------- args ----------
const argv = process.argv.slice(2);
function arg(name, def) {
  const i = argv.indexOf("--" + name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : def;
}
const MAX_PAGES = parseInt(arg("pages", "3"), 10);
const SORT = arg("sort", ""); // "" = top 30 days (default), "top-all-time", "top-new"
const OUT = path.resolve(arg("out", "output"));
const DELAY = parseInt(arg("delay", "800"), 10); // polite delay between requests (ms)
const REFRESH = argv.includes("--refresh"); // re-download & refresh memes already on disk

// Video (mp4) templates have no static image; convert them to a compact gif with
// ffmpeg (must be on PATH). Tune size/quality here, or pass --no-video to skip them.
const NO_VIDEO = argv.includes("--no-video");
const GIF_WIDTH = parseInt(arg("gif-width", "400"), 10); // output width in px (height auto)
const GIF_FPS = parseInt(arg("gif-fps", "12"), 10); // frames per second
const GIF_SECONDS = parseInt(arg("gif-seconds", "6"), 10); // cap duration to keep gifs small
const HAS_FFMPEG = !NO_VIDEO && haveFfmpeg();

const IMAGES_DIR = path.join(OUT, "images");
const META_DIR = path.join(OUT, "meta");

// ---------- helpers ----------
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ScrapMeme/1.0 (educational; public content)";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function fetch(url, binary = false) {
  return new Promise((resolve, reject) => {
    const u = url.startsWith("//") ? "https:" + url : url;
    https
      .get(u, { headers: { "User-Agent": UA, "Accept-Encoding": "identity" } }, (res) => {
        // follow redirects
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          res.resume();
          const loc = res.headers.location.startsWith("http")
            ? res.headers.location
            : new URL(res.headers.location, u).href;
          return resolve(fetch(loc, binary));
        }
        if (res.statusCode !== 200) {
          res.resume();
          return reject(new Error(`HTTP ${res.statusCode} for ${u}`));
        }
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () => resolve(binary ? Buffer.concat(chunks) : Buffer.concat(chunks).toString("utf8")));
      })
      .on("error", reject);
  });
}

function decodeEntities(s) {
  return s
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#0?39;/g, "'")
    .replace(/&apos;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&nbsp;/g, " ")
    .trim();
}

function safeName(s) {
  return s.replace(/[^a-zA-Z0-9._-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 120) || "meme";
}

function haveFfmpeg() {
  try {
    return spawnSync("ffmpeg", ["-version"], { stdio: "ignore" }).status === 0;
  } catch {
    return false;
  }
}

// Convert an mp4 buffer to a compact animated gif (two-pass palette for quality).
// Returns the gif bytes, or null on failure.
function mp4ToGif(mp4Buf) {
  const stamp = `${Date.now()}_${Math.random().toString(36).slice(2)}`;
  const mp4 = path.join(OUT, `.tmp_${stamp}.mp4`);
  const pal = path.join(OUT, `.tmp_${stamp}.png`);
  const gif = path.join(OUT, `.tmp_${stamp}.gif`);
  const vf = `fps=${GIF_FPS},scale=${GIF_WIDTH}:-2:flags=lanczos`;
  try {
    fs.writeFileSync(mp4, mp4Buf);
    const pass1 = spawnSync("ffmpeg", ["-y", "-t", String(GIF_SECONDS), "-i", mp4, "-vf", `${vf},palettegen`, pal], { stdio: "ignore" });
    if (pass1.status !== 0) return null;
    const pass2 = spawnSync("ffmpeg", ["-y", "-t", String(GIF_SECONDS), "-i", mp4, "-i", pal, "-lavfi", `${vf}[x];[x][1:v]paletteuse`, "-loop", "0", gif], { stdio: "ignore" });
    if (pass2.status !== 0) return null;
    return fs.readFileSync(gif);
  } catch {
    return null;
  } finally {
    for (const f of [mp4, pal, gif]) {
      try {
        fs.unlinkSync(f);
      } catch {
        /* ignore */
      }
    }
  }
}

// ---------- parsing ----------
// Parse a /memetemplates listing page into [{ title, slug, memeUrl, imageUrl }].
// The thumbnail in each box IS the blank template, served at a reduced size via
// a "/<n>/" path segment (e.g. //i.imgflip.com/4/30b1gx.jpg). Stripping that
// segment yields the full-resolution blank template (//i.imgflip.com/30b1gx.jpg).
function parseListing(html) {
  const items = [];
  const re =
    /<h3 class="mt-title">\s*<a title="([^"]*)" href="(\/meme\/[^"]+)">([\s\S]*?)<\/a>[\s\S]*?<img[^>]+src="(\/\/i\.imgflip\.com\/[^"]+)"/g;
  let m;
  const seen = new Set();
  while ((m = re.exec(html)) !== null) {
    const slug = m[2].replace("/meme/", "");
    if (seen.has(slug)) continue;
    seen.add(slug);
    const title = decodeEntities(m[3].replace(/<[^>]+>/g, ""));
    const thumb = m[4];
    const fullRes = "https:" + thumb.replace(/(i\.imgflip\.com)\/\d+\//, "$1/");
    items.push({ title, slug, memeUrl: "https://imgflip.com" + m[2], imageUrl: fullRes });
  }
  return items;
}

function hasNextPage(html) {
  return /class='pager-next[^']*'\s+href='([^']+)'/.test(html) || /pager-next[^>]*href="([^"]+)"/.test(html);
}

// Pull the tags from an individual /meme/<Slug> page (image comes from listing).
function parseMemeTags(html) {
  // tags: alternate names ("aka: a, b, c") + keywords meta
  const tags = new Set();
  const alt = html.match(/<div class=['"]alt-names['"]>([\s\S]*?)<\/div>/);
  if (alt) {
    decodeEntities(alt[1].replace(/<[^>]+>/g, ""))
      .replace(/^aka:\s*/i, "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
      .forEach((t) => tags.add(t));
  }
  const kw = html.match(/name="keywords"\s+content="([^"]*)"/);
  if (kw) {
    decodeEntities(kw[1])
      .split(",")
      .map((s) => s.trim())
      .filter((t) => t && !/^(meme|funny|caption)$/i.test(t))
      .forEach((t) => tags.add(t));
  }

  return [...tags];
}

// ---------- main ----------
function csvCell(v) {
  const s = String(v == null ? "" : v);
  return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

(async () => {
  fs.mkdirSync(IMAGES_DIR, { recursive: true });
  fs.mkdirSync(META_DIR, { recursive: true });

  // Load what we already scraped so re-runs accumulate instead of overwriting,
  // and we can skip re-downloading templates we already have (deduped by slug).
  const bySlug = new Map();
  if (fs.existsSync(META_DIR)) {
    for (const f of fs.readdirSync(META_DIR)) {
      if (!f.endsWith(".json")) continue;
      try {
        const rec = JSON.parse(fs.readFileSync(path.join(META_DIR, f), "utf8"));
        if (rec && rec.slug) bySlug.set(rec.slug, rec);
      } catch {
        /* ignore an unreadable sidecar */
      }
    }
  }
  console.log(`Loaded ${bySlug.size} existing memes${REFRESH ? " (--refresh: will re-download)" : " (will skip these)"}`);

  let added = 0;
  let skipped = 0;
  const seenGlobal = new Set(); // dedup templates that appear on more than one page
  for (let page = 1; page <= MAX_PAGES; page++) {
    const qs = new URLSearchParams();
    if (SORT) qs.set("sort", SORT);
    if (page > 1) qs.set("page", String(page));
    const listUrl = "https://imgflip.com/memetemplates" + (qs.toString() ? "?" + qs.toString() : "");
    process.stdout.write(`\n[page ${page}] ${listUrl}\n`);

    let listHtml;
    try {
      listHtml = await fetch(listUrl);
    } catch (e) {
      console.error(`  ! failed to load listing: ${e.message}`);
      break;
    }
    const items = parseListing(listHtml);
    console.log(`  found ${items.length} templates`);

    for (const it of items) {
      if (seenGlobal.has(it.slug)) continue; // already seen on an earlier page this run
      seenGlobal.add(it.slug);
      if (bySlug.has(it.slug) && !REFRESH) {
        skipped++;
        continue; // already on disk — skip without re-downloading
      }
      await sleep(DELAY);
      try {
        // The listing thumbnail's extension (usually .jpg) is not always the
        // template's real format — some blank templates are .png/.gif. Try the
        // derived URL first, then fall back to other extensions until one works.
        const origExt = (it.imageUrl.match(/\.(jpg|jpeg|png|gif)(?:\?|$)/i) || [, "jpg"])[1].toLowerCase();
        const noExt = it.imageUrl.replace(/\.(jpg|jpeg|png|gif)(?:\?|$)/i, "");
        const candidates = [...new Set([origExt, "png", "gif", "jpg"])];

        let buf = null,
          imgUrl = null,
          ext = origExt;
        for (const e of candidates) {
          const url = `${noExt}.${e}`;
          try {
            buf = await fetch(url, true);
            imgUrl = url;
            ext = e;
            break;
          } catch (err) {
            if (!/HTTP 404/.test(err.message)) throw err; // real error, don't mask it
          }
        }
        // No static image at any extension — almost always a video template
        // (only an .mp4 exists). Convert that mp4 into a compact animated gif.
        if (!buf) {
          if (!HAS_FFMPEG) {
            console.log(`  - ${it.title}: skipped (video; ${NO_VIDEO ? "--no-video" : "ffmpeg not found"})`);
            continue;
          }
          let mp4 = null;
          try {
            mp4 = await fetch(`${noExt}.mp4`, true);
          } catch {
            /* not an mp4 either */
          }
          const gifBuf = mp4 && mp4ToGif(mp4);
          if (!gifBuf) {
            console.log(`  - ${it.title}: skipped (no static image; mp4->gif ${mp4 ? "failed" : "unavailable"})`);
            continue;
          }
          buf = gifBuf;
          ext = "gif";
          imgUrl = `${noExt}.mp4`;
          console.log(`    (mp4 -> gif, ${(gifBuf.length / 1024).toFixed(0)} KB)`);
        }

        const base = safeName(it.slug);
        const imgFile = path.join(IMAGES_DIR, `${base}.${ext}`);
        fs.writeFileSync(imgFile, buf);

        // fetch the meme page only for its tags
        let tags = [];
        try {
          tags = parseMemeTags(await fetch(it.memeUrl));
        } catch (e) {
          console.error(`    (tags unavailable for ${it.title}: ${e.message})`);
        }

        const record = {
          title: it.title,
          slug: it.slug,
          tags,
          image_file: path.relative(OUT, imgFile).replace(/\\/g, "/"),
          image_url: imgUrl,
          page_url: it.memeUrl,
        };
        // sidecar alongside the image so the title+tags travel with it
        fs.writeFileSync(path.join(META_DIR, `${base}.json`), JSON.stringify(record, null, 2));
        bySlug.set(it.slug, record);
        added++;
        console.log(`  + ${it.title}  [${tags.length} tags]`);
      } catch (e) {
        console.error(`  ! ${it.title}: ${e.message}`);
      }
    }

    if (!hasNextPage(listHtml)) {
      console.log("\n(no further pages)");
      break;
    }
  }

  // combined manifests, rebuilt from everything we have (old + new), by title
  const records = [...bySlug.values()].sort((a, b) =>
    String(a.title || "").toLowerCase().localeCompare(String(b.title || "").toLowerCase())
  );
  fs.writeFileSync(path.join(OUT, "memes.json"), JSON.stringify(records, null, 2));
  const csv = ["title,slug,tags,image_file,image_url,page_url"]
    .concat(
      records.map((r) =>
        [r.title, r.slug, (r.tags || []).join("; "), r.image_file, r.image_url, r.page_url].map(csvCell).join(",")
      )
    )
    .join("\n");
  fs.writeFileSync(path.join(OUT, "memes.csv"), csv);

  console.log(`\nDone. +${added} new, ${skipped} already had, ${records.length} total in ${OUT}`);
  console.log(`  images -> ${IMAGES_DIR}`);
  console.log(`  per-image title+tags -> ${META_DIR}`);
  console.log(`  combined -> memes.json, memes.csv`);
})();

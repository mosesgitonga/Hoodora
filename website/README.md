# hoodora.one: the public website

One static page, built for search first. It is plain HTML with its styles inline
and no JavaScript, so it loads fast on a slow phone, which Google ranks on. Open
`index.html` in a browser to see it locally.

## What's in it for search engines

- **Title and description:** "neighbourhood app", "Kenya", local news, jobs,
  buy and sell, near you. The phrases people search.
- **Headings:** one `h1` ("The neighbourhood app for Kenya"), then an `h2` per
  section and an `h3` per feature.
- **Content:** about 1,000 words of real content.
- **Structured data** (JSON-LD in the `<head>`): Organization, WebSite,
  WebPage, MobileApplication (free, Android, Kenya) and FAQPage.
  - The FAQ answers there must stay word for word the same as the visible FAQ.
- **Canonical link, hreflang and locale:** one address, `https://hoodora.one/`,
  in English for Kenya (`en-KE`). The nginx site redirects `www` to it.
- **Sharing:** Open Graph and Twitter cards, with
  `images/hoodora-social-card.jpg` (1200 × 630).
- **Crawling:** `robots.txt`, `sitemap.xml` (with the images), and a `404.html`
  marked noindex.
- **Speed:**
  - fonts are self-hosted and cut down to Latin (32 KB and 20 KB);
  - the hero image is preloaded;
  - every image has a width and height, so nothing jumps while loading;
  - images below the first screen load lazily;
  - WebP is served, with JPEG as a fallback.
- **Accessibility:** a skip link, descriptive alt text, focus outlines, and the
  FAQ built on `<details>`, which needs no script.

## Image slots

Replace a file with your own under **the same name and size** and the page picks
it up. Each slot is marked in `index.html` with an `IMAGE SLOT` comment.

| Slot | Files | Size | Now |
| --- | --- | --- | --- |
| `hero`, top of the page | `images/neighbours-community-garden-480.webp`, `-480.jpg`, `-740.webp`, `-740.jpg` | 480 × 360 and 740 × 555 (4:3) | Neighbours joining hands in a community garden |
| `circle`, "How it works" | `images/community-circle-aerial-480.webp`, `-480.jpg`, `-736.webp`, `-736.jpg` | 480 × 480 and 736 × 736 (square, shown as a circle) | A community sitting in a circle, from above |
| `screen-feed` | `images/app-screen-neighbourhood-feed.webp` | 540 × 1170 | Placeholder: replace with an app screenshot |
| `screen-market` | `images/app-screen-marketplace.webp` | 540 × 1170 | Placeholder |
| `screen-jobs` | `images/app-screen-jobs-services.webp` | 540 × 1170 | Placeholder |
| Social card | `images/hoodora-social-card.jpg` | 1200 × 630 | Logo, headline and the hero photo |

**Using a new photo with a different name:**
- update its `src`, `srcset` and preload link in `index.html`;
- update its line in `sitemap.xml`;
- give it a new `alt` text that says what the picture shows.

File names and alt text both count for image search.

**Screenshots:** take them on a test account with made-up content. A real one
would publish someone's name, area or messages.

## Putting it live

1. **DNS:** an `A` record for `hoodora.one` (`@`) and one for `www`, both to
   `77.237.238.14`.
2. **Server:**
   - install `deploy/vps/nginx-hoodora-website.conf` as
     `/etc/nginx/sites-available/hoodora.one`, enable it, then
     `nginx -t && systemctl reload nginx`;
   - run `certbot --nginx -d hoodora.one -d www.hoodora.one`;
   - make `/srv/hoodora-website`. From then on, `deploy.sh` copies this folder
     there on every deploy.
3. **Google Search Console:**
   - add `hoodora.one` as a Domain property, verified with a DNS TXT record;
   - submit `https://hoodora.one/sitemap.xml`;
   - request indexing of the home page.
4. **When the app is on Google Play:**
   - turn the "Coming soon" note in the download section into a link to
     `https://play.google.com/store/apps/details?id=app.hoodora`;
   - update `lastmod` in `sitemap.xml` whenever the page changes.

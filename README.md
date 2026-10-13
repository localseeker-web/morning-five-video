# Morning Five video

Each morning this builds a short vertical video (1080×1920, about 40 seconds) from the day's
brief on ncrnow.ca and theseeker.ca, and posts it as a Reel on each site's Facebook Page.
TikTok will be added once the TikTok developer app is approved.

## How it runs
- `.github/workflows/daily-video.yml` runs every 30 minutes between 7 and 10:30 a.m. (Toronto time, summer).
  It does nothing until a site's brief for today is published, and never posts the same day twice
  (see `state/posted.json`).
- The video text comes from the brief's `<h2>` headlines. The brief writer also adds a hidden comment
  `<!-- morning-five-video: {"stories":[{"tag":"...","fact":"..."}]} -->` with a short topic tag and key fact
  per story. Without it, the video uses a trimmed first sentence (or just the headline).
- Each run's videos are kept for 14 days under the run's **Artifacts** on the Actions tab.

## Settings
- `config.json`: sites, colours, fonts, titles, hashtags. A site is skipped while `"enabled": false`.
- `assets/<site>/logo.png` and `assets/<site>/music.mp3`.
- Repository secrets (Settings → Secrets and variables → Actions):
  `NCRNOW_FB_PAGE_TOKEN`, `SEEKER_FB_PAGE_TOKEN` (Facebook Page access tokens).

## Run it by hand
Actions → **Daily brief videos** → **Run workflow**. Leave "don't post" ticked for a test video.

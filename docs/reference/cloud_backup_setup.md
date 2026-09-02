# Cloud Backup Setup (Cloudflare R2)

One-time setup to back up the raw EDGAR cache (`data/raw`, ~121GB) off this
machine. The cache is the only non-rebuildable asset: code and corrections are
in git, `data/output` rebuilds from the cache, but the cache itself would take
weeks of rate-limited EDGAR downloads to recreate.

Cost: R2 storage is $0.015/GB-month with zero egress fees -> ~$1.85/month for
121GB. The first 10GB is free.

## One-time setup (manual steps, ~10 minutes)

1. **Create a Cloudflare account** (free plan is fine): https://dash.cloudflare.com/sign-up

2. **Enable R2** in the dashboard (R2 Object Storage in the left nav). Requires
   adding a payment card even below the free tier.

3. **Create the bucket**: name `pmw-backup`, location "Automatic", default
   (private) visibility. Keep it PRIVATE -- it needs no public access.

4. **Create an API token**: R2 -> "Manage R2 API Tokens" -> "Create API token".
   - Permissions: **Object Read & Write**
   - Scope: **Apply to specific buckets only** -> `pmw-backup`
   - Note the three values shown once: Access Key ID, Secret Access Key, and
     your Account ID (visible in the R2 overview URL / right sidebar).

5. **Install rclone**:

   ```powershell
   winget install Rclone.Rclone
   ```

   (Open a new shell afterwards so PATH updates.)

6. **Configure the remote** (non-interactive; paste your three values):

   ```powershell
   rclone config create r2 s3 `
     provider=Cloudflare `
     access_key_id=YOUR_ACCESS_KEY_ID `
     secret_access_key=YOUR_SECRET_ACCESS_KEY `
     endpoint=https://YOUR_ACCOUNT_ID.r2.cloudflarestorage.com `
     acl=private
   ```

   Credentials land in `%APPDATA%\rclone\rclone.conf` -- outside the repo, so
   nothing can leak into git.

7. **Verify**:

   ```powershell
   rclone lsd r2:            # should list pmw-backup
   ```

## Running a backup

```powershell
.\scripts\backup_raw_to_r2.ps1 -DryRun    # first time: preview
.\scripts\backup_raw_to_r2.ps1            # sync data/raw (~121GB first run)
.\scripts\backup_raw_to_r2.ps1 -IncludeSnapshots   # + baseline snapshots
```

The first sync uploads everything and is bandwidth-bound (at 100 Mbps expect
roughly 3 hours; leave it running). Subsequent runs transfer only new/changed
files -- minutes, not hours. Logs go to `data/output/r2_backup_<stamp>.log`.

Cadence: run after each quarter's ingest (new filings landed in the cache), or
monthly. Manual is fine; if you want it automatic, register the script in
Windows Task Scheduler.

`rclone sync` mirrors deletions: if you prune the local cache, the bucket
follows. If you ever want the bucket to retain pruned files, edit the script
to use `rclone copy` instead.

## Restore (disaster recovery)

```powershell
rclone sync r2:pmw-backup/data/raw "C:\path\to\repo\data\raw" --transfers 8 --fast-list
```

Then rebuild outputs from the restored cache: `python scripts/rebuild_outputs.py`.

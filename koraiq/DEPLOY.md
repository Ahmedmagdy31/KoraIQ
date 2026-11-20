# Deploying KoraIQ on a single VPS

Whole backend (API, worker, PostgreSQL, Redis, HTTPS) on one small Linux server with Docker.
Time: about 1–2 hours the first time. Files used: everything in `deploy/`.

## 0. What you need

| Item | Notes |
|---|---|
| VPS | Ubuntu 24.04, **2 vCPU / 4 GB RAM / 40 GB disk** (e.g. Hetzner CX22 in Germany/Finland, or DigitalOcean in Frankfurt; roughly €4–7/month, check current prices). EU locations give ~60–80 ms to Egypt, which is fine for this app. |
| Domain | e.g. `koraiq.app`; you'll use `api.koraiq.app` for the backend |
| Firebase project | Same Google account you'll use for AdMob and Play Console |
| SSH key | `ssh-keygen -t ed25519` on your laptop if you don't have one; add the public key when creating the VPS |

## 1. Prepare the server (once)

```bash
ssh root@<SERVER_IP>
apt-get install -y git && git clone <your-repo-url> /root/koraiq   # or scp the zip
bash /root/koraiq/deploy/server-setup.sh     # firewall, auto-updates, swap, Docker, 'deploy' user
```

Open a **second** terminal and check `ssh deploy@<SERVER_IP>` works before closing the root session
(the script disables root and password login).

## 2. DNS

At your domain registrar add an **A record**: `api` → `<SERVER_IP>`. Wait until `ping api.koraiq.app`
shows the server IP (usually minutes).

## 3. Firebase + Google Cloud (once)

1. Firebase console → create project → **Authentication** → enable **Google** and **Anonymous** providers.
2. Project settings → Service accounts → **Generate new private key** → save as `firebase.json`.
3. In the linked Google Cloud project: enable **Google Play Integrity API**, and give the same service account
   access to it (Play Console → App integrity → link the Cloud project).
4. Note the Cloud **project number** (needed by the app build).

## 4. Configure and start

```bash
ssh deploy@<SERVER_IP>
git clone <your-repo-url> ~/koraiq && cd ~/koraiq
cp deploy/.env.example deploy/.env
nano deploy/.env          # DOMAIN, ACME_EMAIL, POSTGRES_PASSWORD (openssl rand -hex 24)
# copy the key from your laptop:  scp firebase.json deploy@<SERVER_IP>:~/koraiq/deploy/secrets/
chmod 444 deploy/secrets/firebase.json

docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env up -d --build
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env run --rm migrate python -m scripts.seed_questions
curl https://api.koraiq.app/readyz          # {"db":true,"redis":true}
```

Caddy gets the HTTPS certificate automatically on first start (ports 80/443 must be open, DNS must point here).

Make yourself admin (to add fixtures/questions):

```bash
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env exec api python -c \
 "from app.security.auth import firebase_app; from firebase_admin import auth; firebase_app(); \
  auth.set_custom_user_claims('<YOUR_FIREBASE_UID>', {'admin': True})"
```
(Your UID is in Firebase console → Authentication → Users, after you sign in to the app once.)

## 5. Backups, monitoring, updates

```bash
crontab -e
15 3 * * * /home/deploy/koraiq/deploy/backup.sh >> /home/deploy/backup.log 2>&1
```
- **Off-site copy:** install `rclone`, run `rclone config` once, then set `RCLONE_REMOTE=remote:bucket/koraiq`
  in the crontab line. A backup on the same disk dies with the disk.
- **Test a restore once:** `docker compose ... exec -T db pg_restore -U koraiq -d koraiq --clean < deploy/backups/<file>.dump`
- **Uptime alert:** free monitor (e.g. UptimeRobot) on `https://api.koraiq.app/readyz`.
- **Logs:** `docker compose -f deploy/docker-compose.prod.yml logs -f api worker`
- **Update to a new version:** `./deploy/update.sh` (pulls, rebuilds, runs migrations first, restarts).
- Also turn on your VPS provider's snapshot/backup option (small monthly fee) as a second safety net.

## 6. AdMob

1. Create the app in AdMob, then three ad units: banner, interstitial, rewarded.
2. For the **rewarded** unit → Server-side verification → callback URL
   `https://api.koraiq.app/api/v1/webhooks/admob-ssv` → **Verify URL** (should succeed).
3. Put the rewarded unit's numeric id (the part after `/`) in `ADMOB_ALLOWED_AD_UNITS` in `deploy/.env`, then
   `./deploy/update.sh`.

## 7. Build and publish the Android app

See `mobile/README.md` for first-time setup, then:

```bash
ADMOB_APP_ID=ca-app-pub-XXXX~YYYY flutter build appbundle --release \
  --dart-define=API_BASE_URL=https://api.koraiq.app \
  --dart-define=CLOUD_PROJECT_NUMBER=<number from step 3> \
  --dart-define=ADMOB_BANNER_ID=ca-app-pub-XXXX/1111 \
  --dart-define=ADMOB_INTERSTITIAL_ID=ca-app-pub-XXXX/2222 \
  --dart-define=ADMOB_REWARDED_ID=ca-app-pub-XXXX/3333
```

Play Console:
1. Upload the `.aab` to **Internal testing** first, then Closed testing (new personal developer accounts must run
   a closed test with testers for a period before production; check the current requirement in Play Console).
2. App content: privacy policy URL, **Data safety** (app activity, name/email via Google sign-in, device IDs for
   ads and fraud prevention), target audience **13+**, ads = yes,
   **account deletion URL** = `https://api.koraiq.app/account-deletion`.
3. After the first upload, copy the **app signing key SHA-256** (Setup → App signing) into
   `INTEGRITY_ALLOWED_CERT_SHA256` (base64url, no padding) and switch `INTEGRITY_MODE` to `enforce` when you're ready.

## 8. Content before going public

Real prizes are gone (v2): weekly winners get coins, an exclusive frame and badges. What's left is content:
each topic appears in the app automatically once it has `TOPIC_MIN_QUESTIONS` (default 10) active questions,
but aim for ~150 reviewed questions per topic before marketing. Add questions with `POST /api/v1/admin/questions`
(set `reviewed_by`), and watch `GET /api/v1/admin/questions/reported`. Regional dialect questions should be
added only after review by a native speaker from that region.

For Ramadan, set `RAMADAN_RANGES=[["2027-02-08","2027-03-09"]]` in `deploy/.env` once the dates are
announced (check the official announcement; dates depend on moon sighting), then `./deploy/update.sh`.

## When to outgrow one VPS

Upgrade the VPS size first (one click at most providers). Move PostgreSQL to a managed database when
backups/restores become a worry or you need zero-downtime upgrades; the app only needs a new `DATABASE_URL`.

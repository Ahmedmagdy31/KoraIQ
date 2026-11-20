# KoraIQ — Egyptian Trivia: Football, Places, Kitchen, Proverbs

Production-ready MVP built from the Master Blueprint. Read **[ARCHITECTURE.md](ARCHITECTURE.md)** first:
it lists every correction and enhancement made to the blueprint and the non-code launch checklist.
To put it on a server, follow **[DEPLOY.md](DEPLOY.md)** (single VPS, Docker, automatic HTTPS).

```
backend/   FastAPI · SQLAlchemy 2 (async) · Alembic · PostgreSQL 16 · Redis · Firebase Admin · APScheduler worker
mobile/    Flutter (Android) · Riverpod · go_router · gen-l10n (ar-EG default, en) · AdMob + UMP · Play Integrity
```

## Run the backend locally (5 minutes)

```bash
cp backend/.env.example backend/.env           # AUTH_MODE=dev for local testing
docker compose up --build -d                    # db, redis, migrate, api, worker
docker compose run --rm migrate python -m scripts.seed_questions
open http://localhost:8080/docs                 # Swagger (disabled when ENV=production)
```

Dev auth: `Authorization: Bearer dev:<any-uid>` (append `:admin` for admin routes, `:guest` for a guest).
Refused at boot unless `ENV` is `development`/`test`.

## Tests

```bash
cd backend && pip install -r requirements-dev.txt
TEST_DATABASE_URL=postgresql+asyncpg://postgres@localhost:5432/koraiq_test \
TEST_REDIS_URL=redis://localhost:6379/15 pytest      # 37 integration + unit tests on real Postgres/Redis
cd ../mobile && flutter test                          # incl. cross-language AES-GCM contract test
```

## API surface (`/api/v1`)

| Method | Path | Notes |
|---|---|---|
| POST | `/auth/sync` | upsert after every sign-in |
| GET/PATCH/DELETE | `/users/me` | DELETE = immediate total erasure |
| POST | `/users/me/onboarding` | nickname, club (locked after), 13+ age gate, terms version |
| GET | `/topics` | visible topics + my mastery tier |
| POST | `/game/start {topic}` · `/game/{id}/answer` · `/resume` · `/finish` · `/fifty` | sealed questions, server clock; 50/50 = coins + unranked |
| GET/POST | `/daily` · `/daily/start` | Daily Challenge: 5 shared questions, 1 attempt, free |
| GET | `/me/progress` · `/me/wallet` | XP/level, streak, mastery, badges; coin history |
| GET/POST | `/shop` · `/shop/buy` · `/me/equip` | streak freezes, extra lives, cosmetics (coins only, never money) |
| POST | `/questions/report` | 3 distinct reports auto-deactivate a question |
| GET | `/fixtures` · POST `/predictions` | lock = kickoff − 15 min (server UTC) |
| GET | `/leaderboard/weekly?scope=all\|<topic>` | global top 50, club top 10, me, sponsor, countdown |
| POST/GET | `/rewards/intents` | rewarded-ad intents (REVIVE, DOUBLE_PREDICTION, EXTRA_LIFE, COIN_BONUS) |
| GET | `/webhooks/admob-ssv` | public, ECDSA-verified |
| * | `/admin/...` | topics, questions (+reported), calibration, fixtures/settlement, sponsor, winners, bans |
| GET | `/account-deletion` (root) | public page required by Google Play |

## Deploy (recommended: Google Cloud Run + Neon/Supabase + Upstash)

1. Build `backend/Dockerfile`; deploy two services from the same image: `api` (default CMD) and `worker` (`python -m app.worker`, min=max=1, CPU always allocated).
2. Run `alembic upgrade head` as a Cloud Run Job before each release.
3. Set `ENV=production AUTH_MODE=firebase INTEGRITY_MODE=soft|enforce` and the secrets from `.env.example` (Secret Manager).
4. Register the SSV URL `https://<api>/api/v1/webhooks/admob-ssv` on every rewarded ad unit and put the numeric unit ids in `ADMOB_ALLOWED_AD_UNITS`.
5. Grant admin: `firebase_admin.auth.set_custom_user_claims(uid, {"admin": True})`.

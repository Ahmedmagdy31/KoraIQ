# KoraIQ — Solutions Architecture Review & Decisions

> **v2 (Nov 2026):** real prizes removed; topics, progression, coins and the Daily Challenge added. See §7.

Review of the *Master Blueprint* with the corrections and enhancements made in this codebase.
Status legend: **[FIX]** blueprint was wrong or unsafe · **[ENH]** improvement · **[KEEP]** implemented as specified.

---

## 1. System overview

```
 Flutter (Android)                         Cloud Run / any container host
 ┌──────────────────────┐   HTTPS+JWT   ┌──────────────────────────────┐    ┌───────────────┐
 │ Riverpod · go_router │──────────────▶│ FastAPI (stateless, N pods)  │───▶│ PostgreSQL 16 │ source of truth
 │ AES-GCM unseal       │               │  /game /predictions /lb ...  │    └───────────────┘
 │ AdMob + UMP          │               └──────────────┬───────────────┘    ┌───────────────┐
 │ Play Integrity (Kt)  │                              └───────────────────▶│ Redis         │ ZSET cache + rate limits
 └─────────┬────────────┘                                                   └───────────────┘
           │ rewarded ad                ┌──────────────────────────────┐
           ▼                            │ Worker (singleton via PG     │ settle · finalize weeks ·
     Google AdMob ── signed SSV ──────▶ │ advisory lock, hot standby)  │ expire rounds · FCM topics
                     callback (ECDSA)   └──────────────────────────────┘
```

## 2. Corrections to the blueprint

| # | Blueprint said | Problem | What we built |
|---|---|---|---|
| 1 | Pre-fetch 10 questions **and** cap speed bonus by server time **[FIX]** | A full-round `/submit` cannot measure per-question time; pre-fetching plaintext lets a cheater research Q7 while Q1's timer runs. | **Sealed pre-fetch**: all 10 questions download in one call, each AES-256-GCM-encrypted with its own key. Key *i* is released in the response to answer *i-1*. One small round-trip per question (~44-byte key), server owns the clock, plus 2s grace for 3G jitter. |
| 2 | `users.weekly_points` reset every Friday **[FIX]** | Destructive reset = lost history, race conditions at 23:59, no audit trail for prize disputes. | Append-only, idempotent `points_ledger` + per-season `season_scores`. "Reset" is just a new season row; old weeks are snapshotted into `season_results`. |
| 3 | Friday 23:59 Cairo **[FIX detail]** | Egypt re-introduced DST in 2023; fixed UTC+2 math breaks half the year. | `zoneinfo("Africa/Cairo")`, season = Sat 00:00 → next Sat 00:00 local; unit-tested in summer and winter. |
| 4 | `nickname NOT NULL` **[FIX]** | Google sign-in creates the user *before* a nickname exists. | Nullable until onboarding; play endpoints return `428 onboarding_required`. |
| 5 | Auth limit 5 req/min **per IP** **[FIX]** | Egyptian mobile carriers put thousands of users behind one CGNAT IP: this would lock out whole neighbourhoods on derby night. | 60/min per IP **and** 5/min per Firebase UID; all limits atomic Lua sliding window; fail-open if Redis is down. |
| 6 | `PLAY_INTEGRITY_DECRYPTION_KEY` **[FIX]** | Local decryption is the legacy path for classic requests. | **Standard requests** decoded by Google's `decodeIntegrityToken` API; `requestHash = sha256(action:uid:nonce)` + single-use nonce in Redis. No key to leak. |
| 7 | Block rooted devices/emulators outright **[ENH]** | Hard blocks hurt legit users on cheap/unsupported phones. | `INTEGRITY_MODE=soft`: play allowed but **unranked** (no leaderboard/prize impact). `enforce` = 403. A Google outage degrades to unranked, never to a full outage. |
| 8 | SSV with `user_id` + `custom_data=session_id` **[FIX]** | A raw session/fixture id lets one ad view be replayed or redirected. | **Reward intents**: server issues a nonce bound to (user, purpose, ref); SSV must match owner; `transaction_id` unique; signature verified over the *raw* query string (re-encoding breaks it). Revive clock restarts *after* the ad closes. |
| 9 | Settle "ON DELETE CASCADE within 24h" **[ENH]** | Google Play also requires a **web** deletion URL (users who uninstalled). | Immediate in-app delete (DB cascade + Redis purge + Firebase user delete) **and** public bilingual `/account-deletion` page for the Play Console. |
| 10 | Store email for prizes **[ENH: data minimisation]** | Duplicates PII already held by Firebase. | Email is never stored in our DB; fetched from Firebase Auth only at prize fulfilment. Birth date is used once for the 13+ gate and never stored. |
| 11 | APScheduler "in the app" **[FIX]** | With N API workers every job runs N times (double settlements, duplicate pushes). | Separate `worker` process, singleton via `pg_try_advisory_lock`; every job is idempotent anyway. |
| 12 | Club badges "Al Ahly Eagle / Zamalek Knight" **[FIX: legal]** | Club crests are registered trademarks. | Colour-coded generic shields only. Licensing official marks is a sponsorship conversation, not an engineering one. |

## 3. Enhancements beyond the blueprint

* **Anti-cheat depth** — besides the `< 8s` round rule: ≥3 correct answers faster than 0.6s (server-measured) flags the round; 3 strikes auto-ban; flagged rounds award 0 and are kept for review.
* **Exact tie-break** — Redis score = `points·10⁶ + (999 999 − seconds into week)`; Redis ranks are *identical* to the PostgreSQL ordering (`points DESC, last_scored_at ASC`) used for prizes. Cache is self-healing (rebuilt every 10 min / on demand).
* **Look-alike nickname defence** — skeleton key folds Arabic alef/hamza/ta-marbuta/ya variants, diacritics, tatweel, bidi/zero-width chars, case, and *both* Latin leet (3→e) and Franco-Arabic (3→ع, 7→ح) digits; stored in a UNIQUE column so "4hly_Fan" can't impersonate "Ahly_Fan".
* **Club lock** after onboarding — stops "club hopping" to farm a smaller club's top-10 prizes.
* **Per-session option shuffle** — the correct answer isn't always "B" for a memorised question.
* **No-repeat & difficulty ramp** — excludes questions from the player's last 3 rounds; easy → hard within a round; `/admin/questions/calibration` flags questions whose real correct-rate disagrees with their rating.
* **Idempotent everything** — answer retries replay the stored result (flaky 3G), SSV retries are no-ops, settlement is locked + flagged + ledger-unique.
* **Localized push with zero fan-out** — FCM topics `kickoff_ar`, `kickoff_en`, …; kickoff reminders ~60 min before lock, weekly results, daily lives refill.
* **Postponed matches** keep predictions and re-open until the new lock time; cancelled matches void cleanly.
* **Scorecard growth loop** — 4:5 card (fits WhatsApp/FB/IG stories), QR + Play link with `utm_source=scorecard` install referrer.
* **AdMob policy hygiene** — UMP consent before any request, `MaxAdContentRating.T`, no banners in the arena, no interstitial on the first round of a session, 1/3 min cap, rewarded ads preloaded with SSV options set just before `show()`.
* **Cross-language crypto contract test** — the same AES-GCM vector is asserted in `pytest` and `flutter test`.

## 4. Round protocol (server-authoritative)

```
POST /game/start            → {session_id, questions:[{index, nonce, ciphertext}×10], first_key}
  (server: life consumed atomically, current_issued_at = now)
POST /game/{id}/answer {index, selected|null}
  → {answer:{correct, correct_option, points, elapsed_ms}, next:{index,key}|null, status}
  correct   → next key, clock restarts
  wrong     → AWAITING_REVIVE (if unused) | COMPLETED
POST /rewards/intents {REVIVE, ref=session} → watch ad → Google SSV → POST /game/{id}/resume
POST /game/{id}/finish      → closes round, awards points (also done by worker for abandoned rounds)
points = 100 + floor(max(0, 15 − server_elapsed))·10   (max 250/question)
```

## 5. Launch-critical items that are NOT code (owner: product/legal)

1. **Prize competition rules.** Free-to-enter skill contests are generally distinct from gambling, but a rewarded-ad 2× multiplier attached to real prizes should be reviewed by Egyptian counsel. Publish official rules (eligibility 18+ or guardian consent for prize winners, tie-break = earliest to reach the score, how winners are contacted) and state that Google is not a sponsor.
2. **PDPL (Law 151/2020).** Confirm the current status of the Executive Regulations and any controller licensing/registration obligations with the Personal Data Protection Center before launch. Implemented technical controls: minimisation, explicit consent with versioned terms (`TERMS_VERSION` forces re-consent), immediate erasure, no PII in logs.
3. **Play Console**: Data safety form (App activity, Personal info via Google Sign-In, Device IDs for ads/fraud), target audience **13+**, Ads declaration, account-deletion URL `https://<api>/account-deletion`.
4. **Moderation**: an Egyptian moderator must populate `backend/app/data/blocked_terms.txt` (Arabic / Franco-Arabic).
5. **Fixtures source**: admin API today; a licensed data feed (e.g. a commercial football API) is a paid upgrade — do not scrape.
6. **Question bank**: 30 launch questions are fact-checked and avoid facts that change over time; target 500+ before marketing spend (players see 10 per round).

## 6. Scaling notes

* API is stateless → horizontal autoscaling. Hot path per answer: 1 row lock + 2 small updates.
* Leaderboard reads are O(log n) in Redis; PostgreSQL fallback uses `ix_season_scores_rank`.
* Supabase transaction pooler (port 6543) + asyncpg needs prepared statements disabled; use the session pooler or a direct connection.
* Derby-night spike: pre-scale API to ≥3 instances 1h before kickoff (Cloud Run min-instances schedule).

## 7. v2: topics, progression, digital economy (approved design, phases 0–1)

* **No real prizes.** `prize_eligible` and prize texts removed (migration `0002`); weekly top 3 get coins + the
  exclusive `FRAME_CHAMPION` frame + `WEEKLY_PODIUM` badge; each topic's #1 gets `TOPIC_CHAMPION`.
* **Topics** (`topics` table, `questions.topic_id`). A topic is visible only when active AND it has
  `TOPIC_MIN_QUESTIONS` active questions, so a topic can be created early and appears by itself.
  Launch content: Football 30, Tourism & Places 21, Egyptian Kitchen 20, Dialects & Proverbs 12 (proverbs only;
  regional dialect questions wait for native-speaker reviewers).
* **Per-topic boards**: `season_scores` primary key is now `(season, user, scope)`; a mixed round credits each
  topic board with the points of its own questions; predictions also count on the Football board.
* **Progression** (`services/progression.py`), granted only from completed, server-timed rounds (never flagged):
  XP = points/10 + 20, level L→L+1 costs 100 + 50(L−1); Cairo-day streak with freezes; topic mastery
  Bronze 50 / Silver 200 / Gold 600 / Diamond 1,500 correct answers; data-driven badges. A round with zero
  correct answers earns nothing (stops start-and-quit farming).
* **Coins** (`coin_ledger`, idempotent; `users.coins` is a cached balance with a `CHECK >= 0`). Earned by
  playing, badges, streak milestones, weekly results and capped rewarded videos; spent on streak freezes,
  extra lives, cosmetics and 50/50. Coins can't be bought (no Play Billing needed) or transferred.
* **50/50 makes the round unranked**: XP and coins still count, leaderboard points don't, so coins never buy rank.
* **Daily Challenge**: 5 questions per Cairo day (topic rotates), one attempt enforced by a partial unique index,
  free, every question answered; spoiler-free emoji share text.
* **Report a mistake**: one report per user per question; 3 distinct reports deactivate it.
* All tunables (prices, caps, XP curve, tiers, milestones) are server settings: change via env + restart, no app release.

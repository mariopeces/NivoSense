# NivoSense production run: status

Kept by the coordinator (see `orchestration.md`). Last update: 2026-11-22.

- Orca Run: `run_d154a40aeb1c` (objective: NivoSense to production, README section 2 is the definition of done)
- Agent: claude only. Limits (Mario, 2026-11-22): up to 7 builders and 6 gauntlets alive at once while the machine stays responsive (back to 5 builders if it slows down). One active builder per lane only where files would overlap.

## Milestones

| Milestone | State | Date |
|---|---|---|
| P0 Foundations | in progress | started 2026-11-21 |
| P1 Observation data | waiting | |
| P2 Model | waiting | |
| P3 Webcams | waiting | |
| P4 Interface | waiting | |
| P5 Production (go-live) | waiting | |

## Tasks

States: waiting, ready, building, gauntlet rN, merged, blocked.

| Task | Lane | Orca task | Needs | State | PR | Last gauntlet verdicts |
|---|---|---|---|---|---|---|
| T0.1 Rules | A | task_f158ee3c34b4 | - | merged (6c602c5) | #3 | G-Code r3 pass (r1, r2 fail) |
| T0.2 Storage and access | A | task_08987025034c | - | merged (ee23a47); main probe run 44962735294 green | #7 | r2: G-Infra PASS, G-Code PASS on 6d1c14e (r1 both fail) |
| T0.5 Quick fixes live site | E | task_7e715b7ea304 | - | merged (0076035), live verified | #4 | G-Code r1 pass, G-UI light r1 pass |
| T0.6 CI and tooling | A | task_00e7b52d23c4 | T0.1 | fixing after r2 (G-Code r2 running) | #6 | r1 both fail; r2: G-Infra fail (colour rule: CSS custom properties, .js/.jsx, named colours) |
| T0.3 Catalogue and publish | A | task_1ffe0c8b1720 | T0.6, T0.2 | fixing after r1, stacked on plan/t06-ci | #13 | r1: G-Infra PASS, G-Data fail (NaN JSON), G-Code fail (surviving mutations) |
| T0.7 Staging site and freeze | A | task_e15b64036ea2 | T0.2, T0.6 | gauntlet r2 (G-Infra and G-Code running) | #12 | r1: G-Code fail, G-Infra fail (any v* tag could go live) |
| T0.4 QA harness | A | task_befbbf9c4c61 | T0.3, T0.7 | building, stacked on plan/t03-catalog (plan-qa, ctx_976ccb1ec332) | | |
| T1.1 S2 ingest | B | task_597641229107 | T0.4 | gauntlet r1 (G-Data ctx_e3021d8c7200, G-Method ctx_b9104f5cdede; G-Code queued) | #14 | |
| T1.0 Reference sample | B (labeller) | task_428ec7332f23 | T1.1 | building, labeller blind to classifier, on plan/t11-s2-ingest (plan-labeller, ctx_ad484b6bb334) | | |
| T1.2 Observed snow cover | B | task_237efa709fff | T1.1, T1.0, T0.4 | waiting | | |
| T1.3 RGB L1C | B | task_6af538d9ec65 | T1.1, T0.3 | building, stacked on plan/t11-s2-ingest (plan-rgb, ctx_4e549ad175fb) | | |
| T1.4 Gap-fill v1 | B | task_2c113522136f | T1.2 | waiting | | |
| T1.7 Past seasons masks | B | task_2754cb4b378b | T1.2 | waiting | | |
| T1.5 Backfill obs | A | task_b949268ad4cb | T1.2, T1.3, T1.4, T0.2 | waiting | | |
| T1.6 Daily ops obs | A | task_ecc3437d227b | T1.5 | waiting | | |
| T2.1 Domain | C | task_d9763bd6b0a5 | T0.3 | ready for gauntlets (G-Data, G-Method, G-Code queued for a free slot), merges after T0.3 | #15 | |
| T2.2 Forcing study | C | task_769d23832dad | T2.1, T1.7 | building, stacked on plan/t21-domain (plan-forcing); scores wait for T1.7 | | |
| T2.3 Physics + assimilation | C | task_833f794e4a1e | T2.2, T1.2 | waiting | | |
| T2.4 Calibration | C | task_1014a67885c3 | T2.3 | waiting | | |
| T2.5 Model backfill + daily | C (+A) | task_4dc4649dbeee | T2.4, T1.5 | waiting | | |
| T2.6 Validation page | C (+E) | task_92bd0ac7a8f8 | T2.5 | waiting | | |
| T3.1 Cetursa webcams | D | task_2c3ed0791fb6 | T0.3 | r2 pushed (2f28bf1), r2 gauntlets queued; catalogue output pending on T0.3 | #8 | r1: G-Data fail (hotlink age, MD5-only placeholder), G-Code fail (localised feratel placeholders) |
| T3.2 Live DGT cams | D | task_a99c254718d7 | T3.1 | waiting | | |
| T3.3 Bearings and FOV | D | task_5e9b5b26f163 | T3.1 | building, stacked on plan/t31-cetursa (plan-bearings, ctx_2e89613ad377) | | |
| T3.4 Cones and cards | E | task_46be14c32fd4 | T3.3, T4.1 | waiting | | |
| T4.0 Design spec | E (design lead) | task_de79f54a990b | T0.1 | ready, G-UI and G-Code r1 queued | #16 | |
| T4.1 Tokens and shell | E | task_3253e4b3860f | T0.6, T4.0 | building, stacked on plan/t06-ci + plan/t40-design (plan-shell, ctx_9048d1707be4) | | |
| T4.2 Timeline | E | task_0bf307d9e4ae | T4.1, T0.3 | waiting | | |
| T4.3 Layers and legends | E | task_3d88661e1945 | T4.2 | waiting | | |
| T4.4 Basin and river panels | E | task_ff92a85a01b8 | T4.3 (T2.5 data optional, "pendiente" before) | waiting | | |
| T4.5 Mobile, a11y, perf | E | task_8d2518876af4 | T4.4 | waiting | | |
| T5.1 Monitoring and cost | A | task_4a57d4fcc072 | T1.6, T2.5 | waiting | | |
| T5.3 Runbook | A | task_43bd89250104 | T5.1 | waiting | | |
| T5.2 Acceptance on staging | A | task_531b2285ac74 | T5.3, T1.6, T2.5, T2.6, T3.2, T3.4, T4.5, T1.7, T0.5 + both soaks | waiting | | |
| T5.4 Go-live | A | task_c053fc911c14 | T5.2, T5.3 (H5 pre-authorised) | waiting | | |
| T5.5 Live soak | A | task_cdc2a9aee5ae | T5.4 + 7 days | waiting | | |

Coordinator notes on the DAG:
- An Orca Task settles when its builder reports `worker_done` (PR ready for review), before gauntlets and merge.
- Stacked-branch rule (Mario, 2026-11-22; replaces "start only when deps are merged" for code deps): a task may start on a branch stacked on its dependency's branch, or against a local folder instead of the bucket, once the dependency's interface is clear. It **merges** only after every task it needs is merged, rebased onto main, with its gauntlets run on the rebased head. The coordinator sets such Orca Tasks to ready by hand.
- T4.0 Design spec added by Mario (plan commit 51aa990); T4.1 now also needs T4.0 (the Orca Task deps of T4.1 predate this; the coordinator enforces it).
- Quality bar (Mario, 2026-11-22): no gauntlet passes on claims; G-UI and G-Method look at real renders. When two options are close, choose the one a geospatial professional would trust.
- Deps follow the dependency graph in `tasks.md` where it is stricter than a card's "Needs" line: T0.4 also waits for T0.7, T1.1 waits for T0.4, T4.1 waits for T0.6. T4.4 does not wait for T2.5 (shows "pendiente" until model data exists).
- T0.4 card said CRS EPSG:25830, contradicting README D2 (EPSG:32630). Fixed in tasks.md on 2026-11-21 toward the definition of done (typo, no change to the DoD).
- T1.0 runs in a fresh labeller worker (not the lane B builder) so it never sees classifier code.

## Soak checks

| Check | Created | Fires | Automation id | Verdict |
|---|---|---|---|---|
| T1.6 F1 soak | | | | |
| T2.5 F2 soak | | | | |
| T5.5 live soak | | | | |

## Waiting for Mario

0. **Position of the Cetursa Pradollano still (`cetursa-pradollano-c1`).** No source gives its position, so it is listed in the rail but not on the map (T3.1, PR #8). Information only; if Mario knows where the camera stands, T3.3 can add its bearing. Nothing is blocked.

1. **Dedicated buckets (blocked by an org IAM deny policy).** Decision needed: ask a Darwin org admin to create `nivosense-data` and `nivosense-staging` in project `nivosense` (europe-west1), or to add a deny-policy exception for Mario on that project. Every Darwin project denies `storage.buckets.create` to Mario's account and new projects cannot be created; other orgs' projects are not acceptable homes. Recommendation: the admin creates the two buckets (exact commands in `docs/runbook.md` once T0.2 lands). Information only, nothing waits on it: under advance OK item 2 the coordinator continues on the interim layout: prefixes `staging/` and `prod/` in the existing bucket `nivosense-cogs`, with prefix-scoped IAM conditions; moving later is a variable change plus a copy. Nothing is blocked while this waits; the dedicated buckets are a later variable change plus a copy.

Advance OK (README section 4) covers the other escalation cases.

## SLO and QA status

Not available until T5.1.

## Changes of approach and spending

None yet.

## Log

- 2026-11-21: Run `run_d154a40aeb1c` and 35-task DAG created. Mario's advance OK recorded in README section 4. Heartbeat automation `cda12975-2e78-4f49-9a7d-f9d4efbb7357` created (daily 09:00 Europe/Madrid). Started T0.1 (lane A, worktree plan-platform, dispatch ctx_8787b4ed4ede) and T0.5 (lane E, worktree plan-ui, dispatch ctx_cb00ccf53cb1). T0.2 ready, queued behind T0.1 in lane A.
- 2026-11-21: T0.1 PR #3 ready (head 367d105); G-Code round 1 started (dispatch ctx_cbaccf4b9dfe). Builder listed 6 out-of-scope items under Found, not done.
- 2026-11-21: T0.1 G-Code r1 FAIL (HANDOFF_CLAUDE.md lacks history banner; GCP scope lines contradict advance OK). Findings sent to builder (ctx_fb3b418c21dc).
- 2026-11-21: T0.5 PR #4 ready (head 4909a76); G-UI (light) and G-Code round 1 started.
- 2026-11-21: T0.1 fixes pushed (head ad29e83); G-Code round 2 started.
- 2026-11-21: T0.5 G-Code r1 PASS (minor follow-ups: silent except OSError backend/ingest_webcams.py:137; tsconfig not strict). Waiting on G-UI light.
- 2026-11-21: Throughput guidance (msg_474e7ef1e8cd): one builder per lane relaxed when files do not overlap. T0.2 started in plan-infra (ctx_9e7f09f10236); T0.6 started early in plan-ci (ctx_0f6f97451c5a).
- 2026-11-21: T0.5 G-UI light r1 PASS (minor follow-ups: 404 frame not marked offline, exact md5 match, manifest fetch without timeout, favicon 404). PR #4 squash-merged as 0076035; Pages deploy triggered by the merge.
- 2026-11-21: T0.1 round 2 fixes pushed (head d9bcdd3); G-Code round 3 started (ctx_27e16659e72f). Plan typo fixed: T0.4 CRS now EPSG:32630.
- 2026-11-21: Change of approach (T0.2): the local account lacks IAM rights to create buckets/SAs/WIF in darwin-general-sandbox (org policy itself allows public buckets). Coordinator approved building in Darwin project `nivosense` (352045667691, Mario owner, already holds nivosense-cogs/-web, same org policies) under advance OK items 2 and 5. Existing buckets left untouched.
- 2026-11-21: T0.5 done: live site verified after deploy (issuecomment-7054364229): 'Sin escenas disponibles' shown, 8/8 DGT cams offline, no placeholder card. Lane E idle until T0.6 merges (T4.1).
- 2026-11-21: T0.1 G-Code r3 PASS; PR #3 squash-merged as 6c602c5. Follow-ups (non-blocking): README.md:31 hackathon wording; no v* release path defined for fixes after go-live (T5.3 runbook / T5.4 should cover); pages.yml push trigger is path-filtered (T0.7 replaces it).
- 2026-11-21: T0.2 blocked by an org IAM deny policy on storage.buckets.create in every Darwin project (also no project creation). Coordinator decision: no other-org projects, no workaround of the deny; SAs + WIF in project nivosense now; interim storage under staging/ and prod/ prefixes of existing bucket nivosense-cogs with prefix-scoped IAM conditions, if bucket IAM/update rights exist. Dedicated buckets added to Waiting for Mario.
- 2026-11-21: Outage. A network outage at about 01:55 (API ENOTFOUND) killed the T0.6 builder (ctx_0f6f97451c5a, uncommitted work in plan-ci) and the T0.2 builder (ctx_9e7f09f10236, commit 49a346b in plan-infra) mid-task, and the coordinator chat with them; the run stalled about 6 h. Coordinator handover to a new chat. Both dispatches stopped (guarded stop, terminals closed); fresh builders started on the same Tasks in the same worktrees with a recovery brief: T0.6 ctx_3b3936fa57cb, T0.2 ctx_aaa1f0cbfe48. T0.2 continues on the interim nivosense-cogs staging/ and prod/ layout (advance OK item 2); the dedicated-bucket item stays as information only. Workers silent for more than 45 minutes are now checked with worker-show and worker-read.
- 2026-11-21: Run paused by Mario on 2026-11-21. No worker or gauntlet runs; none is to be started, restarted or retried until Mario resumes. T0.2: worktree plan-infra, branch plan/t02-storage at 49a346b (pushed, working tree clean); the restarted builder had re-checked GCP state in project nivosense, so GCP resources made after 49a346b (service accounts, WIF, bucket IAM, repo variables) must be re-inspected on resume before anything is created. T0.6: worktree plan-ci, branch plan/t06-ci with a local, unpushed commit 2d4dd3d ("wip") plus 3 uncommitted files on top; nothing pushed, no PR yet. Both dispatches (ctx_aaa1f0cbfe48, ctx_3b3936fa57cb) are stopped; their terminals are retained, not released. On resume: start fresh builders for both Tasks in the same worktrees with a recovery brief, as after the outage.
- 2026-11-22: Run resumed by Mario, same mandate (README section 4). GCP state in project nivosense re-inspected read-only before anything was created: SAs nivosense-gha-staging and nivosense-gha-prod, WIF pool github with provider nivosense-repo (repo id condition; prod SA bound only to refs/heads/main), prefix-scoped objectAdmin on nivosense-cogs (staging/; staging/ and prod/), CORS, 14-day lifecycle on staging/_scratch/, and the repo variables (DATA_/STAGING_ bucket and prefix) all exist; public read not yet granted; docs/runbook.md not yet committed. Fresh builders with recovery briefs: T0.6 ctx_2a0e2e712a9d (plan-ci, keeps wip commit 2d4dd3d and the uncommitted files), T0.2 ctx_e248982bda91 (plan-infra). Paused dispatches released.
- 2026-11-22: Mario asked for maximum effort and more parallel work. Recorded: T4.0 Design spec (new Orca Task task_de79f54a990b, design lead in plan-design, ctx_343998a361a6); stacked-branch rule; limits raised to 7 builders and 6 gauntlets; quality bar on real renders. Started early under the stacked-branch rule, each in its own child worktree: T0.3 on a branch from plan/t06-ci (plan-catalog, ctx_47dfd38bc970), T2.1 (plan-model, ctx_4c7ee8195baf), T3.1 (plan-webcams, ctx_a867ffda15fb), T1.1 against a local folder (plan-observation, ctx_14ada5544ce7). 7 builders alive.
- 2026-11-22: T0.2 PR #7 ready (runbook from live state, branch probe run 44960713581 green: staging 200, prod 403, no gzip; public read only on managed folders staging/ and prod/). G-Infra and G-Code round 1 started. The main-ref probe can only run after merge: the coordinator checks the storage-probe run on main right after the squash merge.
- 2026-11-22: T2.1 decisions: domain = Parque Nacional U Parque Natural (Espacio Natural Sierra Nevada, 172,238 ha); per Decreto 238/2011 the peripheral protection zone is the Natural Park, no separate polygon exists. Sub-basins stay on MITECO Pfafstetter (keeps cod_uni codes the site uses); its download page has an ALTCHA check, so the builder downloads the two zips once through a normal browser session (no bypass), records URL, date, licence and sha256, and commits a clipped source copy if the licence allows. If that fails it goes on Waiting for Mario.
- 2026-11-22: T0.6 PR #6 ready (CI green run 44960881559 in 35 s; failing trials 44960645571 lint, 44960736562 types, 44960813093 tests; hashed locks pin rasterio 1.4.4 / GDAL 3.10.3 and rio-pmtiles 1.2.2; snow-model cache keyed on content hash, exact hit shown; 54 existing colours baselined with ESLint bulk suppressions). G-Infra and G-Code round 1 started.
- 2026-11-22: T3.1 PR #8 ready (17 feratel views from stations 15110-15114 plus the Pradollano still; 13 live, 5 offline because 15110 and 15114 serve a feratel placeholder, now fingerprinted; positions from feratel player metadata; 25 tests). G-Data and G-Code round 1 started. T0.2 G-Code r1 FAIL: Mario's email in docs/runbook.md; builder told to remove it and rewrite the branch history. Started under the stacked-branch rule: T0.7 on plan/t06-ci (plan-staging) and T3.3 on plan/t31-cetursa (plan-bearings). Alive: 6 builders (T0.2 fixing, T0.3, T0.7, T1.1, T2.1, T3.3, T4.0 counted 7 with the fixer) and 5 gauntlets.
- 2026-11-22: T0.2 G-Infra r1 FAIL (major: iam/iamcredentials/sts API enablement not recorded in docs/runbook.md; minors: no issue on probe failure, broad Bucket-type IAM disjunct, runbook placeholder). Both gauntlets confirm the main-ref line is provable after merge (prod-writer-on-main job + repo_ref binding). Findings sent to the builder. Follow-up for later: branch protection on main.
- 2026-11-22: T0.6 G-Infra r1 and G-Code r1 FAIL on the hard-coded-colour rule only: CSS files not linted, and the bulk-suppression baseline counts literals so new colours inside a suppressed className pass (shown by green throwaway CI runs, PRs #9-#11 closed). All Accept lines otherwise pass (CI under 1 min, lock reproduces with uv, snow cache exact hit). Findings sent to the builder.
- 2026-11-22: T0.2 round 2 pushed (head 6d1c14e): email removed from branch history; API enablement and all audit-log changes in the runbook; bucket IAM narrowed (objectAdmin on object prefixes only, listing via bucket-only objectViewer); probe failure on main opens an issue; branch probe 44961952807 green. G-Infra and G-Code round 2 started.
- 2026-11-22: T3.1 G-Data r1 FAIL (2 F3 majors): hotlinked provider image shown with the age of the frame checked at ingest; MD5-only placeholder detection misses other feratel renditions. Coordinator decision: no F3 exception for hotlinking; the site shows exactly the stored, checked still with its captured_at (local folder now, staging prefix via publish after T0.2/T0.3); add Last-Modified == Date, duplicate-bytes and perceptual placeholder guards.
- 2026-11-22: T3.1 G-Code r1 FAIL: feratel localises its placeholder by language (5 MD5s); only German fingerprinted, no language header sent, so the Spanish placeholder passes as live. Sent to the builder with the G-Data fixes.
- 2026-11-22: T0.7 PR #12 ready (staging-site.yml: main push publishes staging/site/, labelled PR publishes staging/site/pr-N/, staging writer only, no gzip, immutable hashed assets; pages.yml deploys only from v* tags, hourly and post-pipeline runs rebuild the latest v* tag with fresh data; v* deployment policy added to the github-pages environment; preview run 44961917497 green and idempotent). Merge order note: the coordinator must push the T0.5 release tag (v*) on main before merging T0.7, or the hourly live data refresh fails. G-Infra and G-Code round 1 started.
- 2026-11-22: Ready: T0.3 PR #13 (71 tests, CI green 44962170504; live publish of 2 real S2 dates to staging/_scratch; deviation to judge: three concurrency groups catalog-staging/-prod/-promote), T1.1 PR #14 (30 acquisitions match an independent query, 11 dates; 2026-11-10 in, 2026-11-05 out at 9.4% coverage; split datatake on 2026-11-17 kept), T2.1 PR #15 (domain 1722.380 km2 vs legal 172,238 ha; NP and PNat within 0.001 km2 of legal areas; MITECO sub-basins fetched once by browser, sha256 recorded, clipped copy in data/sources/). Gauntlets at the limit of 6: T0.3 G-Infra and G-Data started; T0.3 G-Code, T1.1 x3 and T2.1 x3 queued. Started under the stacked-branch rule: T0.4 on plan/t03-catalog, T1.3 on plan/t11-s2-ingest, T2.2 on plan/t21-domain (archive inventory first).
- 2026-11-22: T0.2 G-Infra r2 PASS at 6d1c14e (minors as follow-ups: probe lists DATA_BUCKET instead of STAGING_BUCKET; main unprotected). T0.3 G-Code round 1 started.
- 2026-11-22: T0.2 G-Code r2 PASS; both gauntlets pass on 6d1c14e. PR #7 squash-merged as ee23a47. Post-merge storage-probe run 44962735294 on main green: prod-writer-on-main wrote staging/ and prod/ (HTTP 200 twice) and deleted the prod probe (204), so the main-ref Accept line is proven. Follow-ups: old commit ca67861 still served by GitHub with the email (purge needs GitHub Support, Mario's call); probe listing assumes DATA_BUCKET == STAGING_BUCKET; pages.yml holds id-token: write on main, so bind the prod writer on workflow_ref later; protect main.
- 2026-11-22: v0.1.0 tag pushed on 0076035 (T0.5 merge, the code live today), the T0.5 hotfix release the plan allows, so the tag-only Pages deploy of T0.7 has a release to rebuild. T0.7 G-Code r1 FAIL: pages.yml would deploy the highest-sorting v* tag on any commit; fix sent (strict semver, ancestor of main, fail loudly).
- 2026-11-22: T0.4 freshness design approved: F1 latency per entry from Earth Search 'created'; dates listed with no entry are missing unless a per-date decision object (catalogue root s2/decisions/<date>_<orbit>.json, schema in T0.4) explains them; T1.1/T1.6 write those objects. T2.2 archive inventory received: no open AEMET HARMONIE archive; ERA5-Land full variables only via CDS (key needed); candidates approved: ecmwf_ifs, icon_eu, gfs_global, arpege_europe, era5_seamless; RIA stations now, AEMET pending key. T0.6 round 2 pushed (per-occurrence colour rule covering CSS, head 6930192, CI 33 s); its r2 gauntlets start at the next free slot (gauntlets at 6).
- 2026-11-22: T0.7 G-Infra r1 FAIL (same tag-selection major; merge gate met by v0.1.0). T3.1 round 2 pushed (2f28bf1): card shows only stored checked stills (content-addressed, local store shipped in the Pages artifact until the bucket store lands), five placeholder guards incl. all 24 feratel renditions and dHash. T0.6 G-Infra r2 started. Gauntlet queue (in order): T0.6 G-Code r2, T1.1 G-Code r1, T3.1 G-Data and G-Code r2, T2.1 G-Data, G-Method, G-Code r1.
- 2026-11-22: T0.7 round 1 fixes pushed (b321cf5): scripts/pick_release.py deploys only the newest strict-semver tag that is an ancestor of origin/main; v* tag ruleset 27815705; github-pages tag policy narrowed; dry run picks v0.1.0, refuses a stray v9.9.9. Post-merge checks owed by the coordinator: main Staging site run green and site/index.html 200; first hourly Publish site logs 'Deploying release v0.1.0'. Queue now: T0.6 G-Code r2, T0.7 G-Infra and G-Code r2, T1.1 G-Code r1, T3.1 r2 x2, T2.1 r1 x3.
- 2026-11-22: T4.0 PR #16 ready (tokens.json, ramps.json from cmocean ice/deep and Crameri acton with order kept under CVD and greyscale, copy.es.json, 13 mockup screens at 1440 and 375, side-by-sides with cedar-vista, openpas and the live site). G-UI and G-Code r1 queued. Started: T4.1 (plan-shell, on plan/t06-ci with plan/t40-design merged) and T1.0 labeller (plan-labeller, on plan/t11-s2-ingest, never sees classifier code or output). Queue: T0.6 G-Code r2, T0.7 r2 x2, T4.0 G-UI, T1.1 G-Code, T3.1 r2 x2, T2.1 r1 x3, T4.0 G-Code.
- 2026-11-22: T0.3 G-Infra r1 PASS (live races with real 412 retries, crash mid-promote leaves index byte-identical; minors: queued promote can be cancelled in catalog-promote, mutation gaps, processing_baseline optional in input_key, no cost estimate, crash orphans not cleaned). T0.6 G-Code r2 started.
- 2026-11-22: T4.1 decision: legacy data-ramp gradients in Legend.tsx that mirror today's pipeline PNG palettes stay in the colour baseline as a declared exception until T4.3 moves legends to ramps.json and re-colours the pipelines (a legend must not lie about the image); hackathon 'Snow cover / Snow change' rail modes dropped in favour of the T4.0 rail with honest empty states.
- 2026-11-22: T0.3 G-Data r1 FAIL (major: NaN nodata written as bare NaN into entry and index.json, invalid JSON). Sent to the builder. T0.7 G-Infra r2 started.
- 2026-11-22: T0.6 G-Infra r2 FAIL on the colour rule again (blocker: CSS custom property values unchecked; majors: named colours and nested-paren functions in TS, .js/.jsx not linted). To bound round 3 the coordinator fixed the bar: all CSS declarations incl. custom properties, all colour syntaxes incl. nested parens, all script extensions, named colours where used as colours (CSS, style props, MapLibre paint, SVG/Recharts colour props), no inline disabling, baseline may only shrink; named colour words in prose strings not required.
- 2026-11-22: T0.3 G-Code r1 FAIL (tests let mutations survive: input_key fields, never-overwrite, promote ordering; no GcsStorage unit test). Sent with the G-Data fixes. T0.7 G-Code r2 started.

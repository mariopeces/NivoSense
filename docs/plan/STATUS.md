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
| T0.2 Storage and access | A | task_08987025034c | - | building (plan-infra, ctx_e248982bda91) | | |
| T0.5 Quick fixes live site | E | task_7e715b7ea304 | - | merged (0076035), live verified | #4 | G-Code r1 pass, G-UI light r1 pass |
| T0.6 CI and tooling | A | task_00e7b52d23c4 | T0.1 | building (plan-ci, ctx_2a0e2e712a9d) | | |
| T0.3 Catalogue and publish | A | task_1ffe0c8b1720 | T0.6, T0.2 | building, stacked on plan/t06-ci (plan-catalog, ctx_47dfd38bc970) | | |
| T0.7 Staging site and freeze | A | task_e15b64036ea2 | T0.2, T0.6 | waiting | | |
| T0.4 QA harness | A | task_befbbf9c4c61 | T0.3, T0.7 | waiting | | |
| T1.1 S2 ingest | B | task_597641229107 | T0.4 | building early, local folder (plan-observation, ctx_14ada5544ce7) | | |
| T1.0 Reference sample | B (labeller) | task_428ec7332f23 | T1.1 | waiting | | |
| T1.2 Observed snow cover | B | task_237efa709fff | T1.1, T1.0, T0.4 | waiting | | |
| T1.3 RGB L1C | B | task_6af538d9ec65 | T1.1, T0.3 | waiting | | |
| T1.4 Gap-fill v1 | B | task_2c113522136f | T1.2 | waiting | | |
| T1.7 Past seasons masks | B | task_2754cb4b378b | T1.2 | waiting | | |
| T1.5 Backfill obs | A | task_b949268ad4cb | T1.2, T1.3, T1.4, T0.2 | waiting | | |
| T1.6 Daily ops obs | A | task_ecc3437d227b | T1.5 | waiting | | |
| T2.1 Domain | C | task_d9763bd6b0a5 | T0.3 | building early (plan-model, ctx_4c7ee8195baf) | | |
| T2.2 Forcing study | C | task_769d23832dad | T2.1, T1.7 | waiting | | |
| T2.3 Physics + assimilation | C | task_833f794e4a1e | T2.2, T1.2 | waiting | | |
| T2.4 Calibration | C | task_1014a67885c3 | T2.3 | waiting | | |
| T2.5 Model backfill + daily | C (+A) | task_4dc4649dbeee | T2.4, T1.5 | waiting | | |
| T2.6 Validation page | C (+E) | task_92bd0ac7a8f8 | T2.5 | waiting | | |
| T3.1 Cetursa webcams | D | task_2c3ed0791fb6 | T0.3 | building early, current webcams.json path (plan-webcams, ctx_a867ffda15fb) | | |
| T3.2 Live DGT cams | D | task_a99c254718d7 | T3.1 | waiting | | |
| T3.3 Bearings and FOV | D | task_5e9b5b26f163 | T3.1 | waiting | | |
| T3.4 Cones and cards | E | task_46be14c32fd4 | T3.3, T4.1 | waiting | | |
| T4.0 Design spec | E (design lead) | task_de79f54a990b | T0.1 | building (plan-design, ctx_343998a361a6) | | |
| T4.1 Tokens and shell | E | task_3253e4b3860f | T0.6, T4.0 | waiting | | |
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

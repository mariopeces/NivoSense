# NivoSense production run: status

Kept by the coordinator (see `orchestration.md`). Last update: 2026-11-21.

- Orca Run: `run_d154a40aeb1c` (objective: NivoSense to production, README section 2 is the definition of done)
- Agent: claude only. Limits: at most 5 builders and about 6 gauntlets alive at once; one active builder per lane.

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
| T0.1 Rules | A | task_f158ee3c34b4 | - | gauntlet r2 (G-Code: ctx_f510cd753f77) | #3 | G-Code r1 fail (2 major, 1 minor) |
| T0.2 Storage and access | A | task_08987025034c | - | ready (lane A busy) | | |
| T0.5 Quick fixes live site | E | task_7e715b7ea304 | - | gauntlet r1 (G-UI light: ctx_46186010bbda, G-Code: ctx_f75556184958) | #4 | G-Code r1 pass (2 minor follow-ups) |
| T0.6 CI and tooling | A | task_00e7b52d23c4 | T0.1 | waiting | | |
| T0.3 Catalogue and publish | A | task_1ffe0c8b1720 | T0.6, T0.2 | waiting | | |
| T0.7 Staging site and freeze | A | task_e15b64036ea2 | T0.2, T0.6 | waiting | | |
| T0.4 QA harness | A | task_befbbf9c4c61 | T0.3, T0.7 | waiting | | |
| T1.1 S2 ingest | B | task_597641229107 | T0.4 | waiting | | |
| T1.0 Reference sample | B (labeller) | task_428ec7332f23 | T1.1 | waiting | | |
| T1.2 Observed snow cover | B | task_237efa709fff | T1.1, T1.0, T0.4 | waiting | | |
| T1.3 RGB L1C | B | task_6af538d9ec65 | T1.1, T0.3 | waiting | | |
| T1.4 Gap-fill v1 | B | task_2c113522136f | T1.2 | waiting | | |
| T1.7 Past seasons masks | B | task_2754cb4b378b | T1.2 | waiting | | |
| T1.5 Backfill obs | A | task_b949268ad4cb | T1.2, T1.3, T1.4, T0.2 | waiting | | |
| T1.6 Daily ops obs | A | task_ecc3437d227b | T1.5 | waiting | | |
| T2.1 Domain | C | task_d9763bd6b0a5 | T0.3 | waiting | | |
| T2.2 Forcing study | C | task_769d23832dad | T2.1, T1.7 | waiting | | |
| T2.3 Physics + assimilation | C | task_833f794e4a1e | T2.2, T1.2 | waiting | | |
| T2.4 Calibration | C | task_1014a67885c3 | T2.3 | waiting | | |
| T2.5 Model backfill + daily | C (+A) | task_4dc4649dbeee | T2.4, T1.5 | waiting | | |
| T2.6 Validation page | C (+E) | task_92bd0ac7a8f8 | T2.5 | waiting | | |
| T3.1 Cetursa webcams | D | task_2c3ed0791fb6 | T0.3 | waiting | | |
| T3.2 Live DGT cams | D | task_a99c254718d7 | T3.1 | waiting | | |
| T3.3 Bearings and FOV | D | task_5e9b5b26f163 | T3.1 | waiting | | |
| T3.4 Cones and cards | E | task_46be14c32fd4 | T3.3, T4.1 | waiting | | |
| T4.1 Tokens and shell | E | task_3253e4b3860f | T0.6 | waiting | | |
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
- An Orca Task settles when its builder reports `worker_done` (PR ready for review), before gauntlets and merge. A dependent task is started only when every task it needs is **merged** in this table, whatever `task-list --ready` says.
- Deps follow the dependency graph in `tasks.md` where it is stricter than a card's "Needs" line: T0.4 also waits for T0.7, T1.1 waits for T0.4, T4.1 waits for T0.6. T4.4 does not wait for T2.5 (shows "pendiente" until model data exists).
- T0.4 card says CRS EPSG:25830; README D2 (definition of done) says EPSG:32630. The builder spec tells T0.4 to check EPSG:32630.
- T1.0 runs in a fresh labeller worker (not the lane B builder) so it never sees classifier code.

## Soak checks

| Check | Created | Fires | Automation id | Verdict |
|---|---|---|---|---|
| T1.6 F1 soak | | | | |
| T2.5 F2 soak | | | | |
| T5.5 live soak | | | | |

## Waiting for Mario

Nothing. Mario gave advance OK on 2026-11-21 for every escalation case (README section 4): H5 go-live authorised, org-policy alternative, third-round decisions by the coordinator, spending above the cap logged, outside actions allowed except messaging people and committing secrets.

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

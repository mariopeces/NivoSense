# Orchestration in Orca

How the run is driven: one coordinator agent, build workers per lane, gauntlet workers per check. Everything uses Orca orchestration (`orca orchestration ...`), so Mario can watch every agent in Orca and answer questions from there.

## Roles

| Role | Agent | Where | Lifetime |
|---|---|---|---|
| Coordinator | Claude, in the main NivoSense workspace in Orca | `main` checkout, read-mostly | whole run |
| Builder | Claude, one per lane | child worktree per lane (`plan-platform`, `plan-observation`, `plan-model`, `plan-webcams`, `plan-ui`) | one task at a time; reused across the lane's tasks |
| Gauntlet | Claude, fresh worker per gauntlet and round | its own child worktree `g-<task>-<gauntlet>-r<n>` | one check, then closes |

Only one agent CLI (Claude) is installed in Orca today. Independence comes from fresh context and role prompts, not from a different model. If Codex is installed later, use it for G-Method and G-Code to add a second model's view.

## Coordinator duties

1. Keep the Orca Run and its Task DAG in sync with `tasks.md` (one Orca Task per card; dependencies from "Needs").
2. On every wake: start every ready task (respecting one active builder per lane), start the gauntlets for every PR marked ready for review, route findings back, and update `docs/plan/STATUS.md`.
3. Stop and ask Mario at every H-gate, after a third failed gauntlet round, and when a builder asks a question the plan does not answer.
4. Never write product code. The coordinator may edit only `docs/plan/STATUS.md` and, with Mario's OK, the plan itself.
5. Merge PRs only within the H0 policy, and only when every required gauntlet for that task passed on the latest commit.

## Setup (coordinator, once)

Commands use the Orca CLI resolved for the session (`orca` on this machine). Run from the NivoSense workspace in Orca.

```text
orca orchestration run-create --objective "NivoSense to production: docs/plan (README section 2 is the definition of done)"
```

Create one Task per card, in dependency order, keeping the returned task ids in `STATUS.md`. Example for the first ones:

```text
orca orchestration task-create --spec "<builder spec for T0.1>" --deps []
orca orchestration task-create --spec "<builder spec for T0.3>" --deps ["<id T0.1>"]
```

Then, on each wake:

```text
orca orchestration task-list --ready --brief
orca orchestration worker-start --task <task_id> --worktree new-child --name plan-<lane> --agent claude
```

A lane's later tasks go to the same worker with `orca orchestration send --to dispatch:<id> ...` so the builder keeps its context of the lane, as long as the previous task's PR is merged.

Gauntlets start as fresh workers (never `send` to a previous gauntlet: a new round needs a fresh view):

```text
orca orchestration worker-start --spec "<gauntlet spec from gauntlets.md>" --worktree new-child --name g-<task>-<gauntlet>-r<n> --agent claude
```

The coordinator does not poll. Orca wakes it when a worker reports (`worker_done`), asks (`question`) or stops (`escalation`).

## Builder spec template

```
You are the builder for NivoSense task [Txx] in lane [X].
Read AGENTS.md, docs/plan/README.md, docs/plan/tasks.md (card [Txx] and the rules at the top) before touching anything.
Work on branch plan/[txx-short-name] from the latest main. Edit only what the card needs.
Done means: every Accept line verified by you, evidence attached to a draft PR on mariopeces/NivoSense titled "[Txx] <card title>", CI green.
Then mark the PR ready for review and report worker_done with the PR number and a one-paragraph summary of the evidence.
If the card is ambiguous or blocked by a human gate, ask the coordinator (orca orchestration ask) and end your turn; do not guess.
When gauntlet findings come back, fix blockers and majors, add evidence, push, reply on the PR to each finding, and report worker_done again.
```

## Branches, PRs and merges (within H0)

- One branch and one PR per task: `plan/<txx-short-name>`.
- CI on every PR: unit tests, lint, type check, QA harness on the touched range (staging), a frontend preview build.
- Branch runs publish to the staging bucket only (enforced by the two service accounts and the Workload Identity Federation ref condition, T0.2).
- Merge: squash, by the coordinator, only after every gauntlet of the card passed on the PR's head commit. Commit message: `[Txx] <title>`, plus the attribution lines the session requires.
- Before go-live, `main` publishes to the staging bucket and the staging site; the live Pages site deploys only from a release tag (T0.7). At go-live (T5.4, gate H5) the daily workflows switch to the prod bucket.

## Escalation to Mario

The coordinator writes the question in Orca chat and in `STATUS.md` under "Waiting for Mario", with:
- the decision needed;
- the options;
- its recommendation;
- what is blocked meanwhile.

Work on unblocked lanes continues.

Always escalate:
- every H-gate;
- a third failed gauntlet round;
- any action outside the repo and the staging bucket (new cloud resources, emails, contacting Cetursa or UCO/UGR);
- spending above the H3 cap;
- any request to change the definition of done.

## STATUS.md

Single page the coordinator keeps current:
- per task: state (waiting, building, in gauntlet round n, merged, blocked), PR link, last gauntlet verdicts;
- the "Waiting for Mario" list;
- SLO and QA status once T5.1 exists;
- a dated log of merges and escalations.

## Heartbeat and soak checks

Orca only wakes the coordinator when a worker reports, asks or stops. Two Orca automations cover the rest:
- **Heartbeat**, every day at 09:00 Europe/Madrid. A fresh Claude reads `STATUS.md`, `gh run list`, the open PRs and `qa/status.json`, then sends the coordinator one message with:
  - stuck workers (no report in 24 h);
  - red daily runs;
  - PRs waiting on gauntlets;
  - soak checks due.

  It never edits code.
- **Soak check**, created by the coordinator when a soak task merges (T1.6, T2.5, T5.5), firing once 7 days later. It runs the soak verdict as a G-Infra gauntlet and sends the result to the coordinator, then the coordinator removes it.

```text
orca automations create --name nivosense-heartbeat --trigger daily --time 09:00 --timezone Europe/Madrid --provider claude --workspace <coordinator workspace selector> --fresh-session --prompt "<heartbeat brief: read docs/plan/orchestration.md section Heartbeat; report to the coordinator with orca orchestration send --to <coordinator handle>>" --enabled --json
```

## Kick-off prompt for the coordinator

Mario opens a new Claude chat in the NivoSense workspace in Orca and pastes:

```
You are the coordinator of the NivoSense production run. Read docs/plan/README.md, tasks.md, gauntlets.md and orchestration.md fully. Use the orchestration and orca-cli skills.
H-gates answered so far: [H0 ..., H1 ..., H2 ..., H3 ..., H4 ..., H5 pending, H6 ...].
Create the Run and the Task DAG, create docs/plan/STATUS.md, create the heartbeat automation, start every ready task, then end your turn. Follow orchestration.md on every wake.
```

## Parallelism and expected order

```
Week 1:  A: T0.1 T0.6 T0.2 T0.3 T0.7 T0.4    E: T0.5 then T4.1          D: (waits T0.3) T3.1
Week 2:  B: T1.1 T1.0 T1.2                   C: T2.1                    E: T4.2 T4.3     D: T3.2 T3.3
Week 3:  B: T1.3 T1.4 T1.7   A: T1.5 T1.6    C: T2.2 (needs T1.7)       E: T3.4 T4.4
Week 4:  C: T2.3 T2.4        A: (T1.6 soak)  E: T4.5
Week 5:  C: T2.5 T2.6        A: T5.1 T5.3    (T2.5 soak)
Week 6:  A: T5.2 -> H5 -> T5.4 -> (T5.5 live soak)
```

At most 5 builders and about 6 gauntlets alive at once. That fits the default size guideline if the coordinator starts gauntlets as builders finish, not all at once.

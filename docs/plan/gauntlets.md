# Gauntlets

A gauntlet is a validation agent with one role, a rubric and the power to send work back. Gauntlets are what make "leave the agents working" safe: no task merges on the builder's word.

## Principles

1. **Fresh context.** A gauntlet agent never shares the builder's conversation. It gets the task card, the PR diff, the evidence and access to the repo, the staging bucket and the staging site. It is not told what the builder thinks is right.
2. **Evidence over claims.** A gauntlet reruns or samples the checks itself (tests, QA harness, its own STAC queries, its own screenshots). A builder's number is a hint, not proof.
3. **Binary verdict, specific findings.** Verdict `pass` or `fail`. Every finding has: severity (blocker, major, minor), where (file:line, layer and date, screen and viewport), what is wrong, how it was observed, and what would make it pass. Minor findings never block; they go to a follow-up list.
4. **Adversarial by default.** Each gauntlet looks for the way the work is wrong, starting from the riskiest claim in the card's "Accept" list.
5. **No moving the bar.** A gauntlet checks the card's "Accept" lines and its own rubric. It cannot add new scope; new ideas go to "Follow-ups".
6. **Bounded loops.** Builder and gauntlet loop at most 3 times per task. A fourth failure goes to Mario as a human decision with both sides' evidence.

## The loop

```
builder: implement -> self-check (tests + QA harness + card evidence) -> open PR (draft) with evidence
   |
coordinator: start the task's gauntlets in parallel, each in a fresh worker
   |
gauntlets: verdict + findings (JSON, schema below) posted as PR comments
   |
all pass? -- yes --> coordinator marks PR ready; merge per H0 policy; task done
   |
   no --> coordinator sends the blocker and major findings to the builder (same worker, follow-up)
          builder fixes, adds evidence, pushes -> gauntlets that failed run again (fresh workers)
          after 3 failed rounds -> escalate to Mario
```

Finding JSON (each gauntlet ends its report with this block):

```json
{
  "gauntlet": "G-Method",
  "task": "T1.2",
  "round": 1,
  "verdict": "fail",
  "findings": [
    {
      "severity": "blocker",
      "where": "pipelines/snow_obs/classify.py:88; date 2026-02-14",
      "what": "Terrain shadow on north faces classified as no snow",
      "observed": "rendered thumbnail + 40 pixels sampled, 31 snow in RGB, 0 in mask",
      "to_pass": "shadow pixels marked unknown, or score of shadow class reported separately"
    }
  ],
  "followups": []
}
```

## The gauntlets

### G-Code (every task)
Role: senior software engineer.
- Tests exist for the new behaviour and pass in CI; a deliberately broken input fails them.
- The change does only what the card says; no dead code, no speculative abstractions, no silent `except`.
- Readable names; comments only where the why is not obvious.
- No secrets, tokens or personal data in code, logs, PR text or published files.
- Types (TypeScript strict, Python type hints on public functions); lint clean.
- Dependencies pinned; new ones justified in the PR.

### G-Method (science and methodology)
Role: remote sensing and snow hydrology reviewer.
- The algorithm matches the method in `README.md` section 6 and the cited literature, or the PR explains why it differs.
- Thresholds, constants and parameters have a source or a calibration that produced them.
- Validation is honest:
  - no leakage (held-out dates really held out; calibration and test seasons separate);
  - metrics computed on the right population (snow season, inside the domain, ski resort excluded);
  - the confusion matrix shown, not only accuracy.
- Known traps checked explicitly: snow/cloud confusion, terrain shadow, forest, mixed pixels at the snowline, swath-edge partial coverage, the c1 reflectance offset, L1C vs L2A geometry, CRS and resampling choices.
- Independent check: the gauntlet hand-labels or samples at least 100 pixels on at least 3 dates it picks itself, from the RGB, without looking at the classifier output first.
- Claims on the site and in docs do not go beyond what the validation shows.

### G-Data (data quality)
Role: data engineer on call.
- Runs `qa/check_catalog` over the range the task touched; zero errors.
- Picks 10 random catalogue entries plus the regression fixtures and inspects the thumbnails from `qa/render_thumbs` (multimodal review): stripes, seams between tiles, misregistration, empty tiles, wrong colour scale, nodata shown as values.
- Compares the catalogue against an independent source query (STAC search for S2 dates; the day list for daily layers).
- Checks idempotency: reruns one date with the same input key (for the model, from the stored state of the day before) and compares `pixel_hash`; timestamps excluded.
- Checks units, value ranges and legend constants against the data.

### G-Infra (infrastructure and operations)
Role: SRE.
- Workflows:
  - concurrency set;
  - timeouts set;
  - retries only where safe;
  - caches keyed correctly;
  - every step idempotent;
  - failures open an issue;
  - the 6 h job limit respected (matrix sizes).
- Access:
  - only Workload Identity Federation;
  - least privilege;
  - branch runs cannot write the prod bucket (two service accounts, ref condition);
  - no long-lived keys anywhere;
  - public read limited to the data prefixes.
- Cost estimate updated when storage or compute changes.
- Can the runbook procedures be followed literally? (T5.3)
- Recovery: catalogue writes atomic; a half-failed run leaves prod readable.

### G-UI (interface)
Role: product designer plus front-end reviewer. Uses Playwright on the staging site (or a local preview build) at 375x812 and 1440x900, plus axe and Lighthouse.

Rubric (each section pass or fail; all must pass for the tasks that touch it):

**A. Visual system**
- Colours, type, radius, shadow from tokens only.
- One display face plus Inter, loaded.
- No text under 12 px.
- No all-caps blocks with wide tracking.
- No glow, no glassmorphism over the map.

**B. Layout**
- Dark icon rail + light panel (cedar-vista pattern).
- Panel collapses.
- Nothing floats over the map except the timeline, legend chips and map controls.
- The map stays the hero.

**C. Information**
- Every layer shows source, resolution, the date of the real observation behind it and its status (observed / gap-filled / modelled / forecast).
- Units always visible.
- Empty and offline states are honest.

**D. Interaction**
- Timeline scrubs the whole history.
- Keyboard works on rail, panel, timeline.
- URL keeps state.
- Hover and selected states are distinct.

**E. Webcams**
- Icon rotated to the bearing.
- Cone matches bearing, field of view and range.
- Card shows the large image, age and credit.
- Offline state.

**F. Quality bar**
- No console errors or failed requests.
- Lighthouse (desktop and mobile presets, median of 3 runs) and axe numbers per README U2.
- Spanish copy without typos or mixed languages.

**G. "Not AI slop" check**
- The gauntlet writes three sentences on whether a geospatial professional would trust this as a product.
- It compares side by side against screenshots of cedar-vista and openpas-habitat.web.app taken in the same run.
- Any "looks generated" element (generic gradients, decorative icons with no meaning, filler copy, inconsistent spacing) is a major finding.

### G-Product (end to end acceptance)
Role: a demanding user and the product owner. Runs on staging for T5.2 and on the live URL for T5.4.
- Walks the user stories:
  1. open the site, see today's snow;
  2. go back to a date in February 2026, compare observed vs gap-filled vs SWE;
  3. open a basin and read its season curve;
  4. open each live webcam, check it looks where its cone says;
  5. scrub the timeline across the year;
  6. open the method page.
- Checks every line of README section 2 with evidence, one by one, and writes a pass/fail table.
- Reports the user-visible problems in order of how much they would hurt trust.

## Running a gauntlet

The coordinator starts each gauntlet as a fresh Orca worker with this spec (fill the brackets):

```
You are the [G-xxx] gauntlet for NivoSense task [Txx] round [n].
Read docs/plan/gauntlets.md (your section and the principles), docs/plan/README.md section 2, and the card for [Txx] in docs/plan/tasks.md.
The work is in PR [#] on branch [branch] of mariopeces/NivoSense; staging data in gs://nivosense-staging/ ; staging site at https://storage.googleapis.com/nivosense-staging/site/index.html (or site/pr-[n]/ for a PR preview).
Do not edit the builder's branch. You may write only under qa-reports/[Txx]/[G-xxx]-round[n]/ in your own worktree.
Verify every Accept line of the card and your rubric with your own evidence. Be adversarial.
Finish with the Finding JSON block. Post your report as a PR comment with `gh pr comment`, then report worker_done with the verdict.
```

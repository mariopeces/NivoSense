# Runbook

Operations procedures for NivoSense. Each section lists the exact commands, run from the repo root with the gcloud account of a `nivosense` project owner. Commands are idempotent unless a note says otherwise: re-running a `create` on an existing resource fails with `ALREADY_EXISTS` and changes nothing.

## 1. Storage and access (T0.2)

### 1.1 Where it lives and why

| What | Value |
|---|---|
| GCP project | `nivosense` (number `352045667691`), Darwin organisation `190458521623` |
| Data bucket (prod) | `gs://nivosense-cogs`, prefix `prod/` (interim, see 1.3) |
| Staging bucket | `gs://nivosense-cogs`, prefix `staging/` (interim, see 1.3) |
| Scratch area | `gs://nivosense-cogs/staging/_scratch/`, deleted after 14 days |
| Staging writer | `nivosense-gha-staging@nivosense.iam.gserviceaccount.com` |
| Prod writer | `nivosense-gha-prod@nivosense.iam.gserviceaccount.com` |
| WIF provider | `projects/352045667691/locations/global/workloadIdentityPools/github/providers/nivosense-repo` |

Code never names the bucket or prefix. Workflows read the repository variables in 1.8 and build object names as `${STAGING_BUCKET}/${STAGING_PREFIX}...` and `${DATA_BUCKET}/${DATA_PREFIX}...`.

### 1.2 Org policy check (2026-11-21, re-checked 2026-11-22)

The Organization Policy API (`orgpolicy.googleapis.com`) is disabled in both projects, so the effective policies were read through the Resource Manager v1 API, which needs nothing enabled:

```sh
for P in darwin-general-sandbox nivosense; do
  for c in storage.publicAccessPrevention iam.allowedPolicyMemberDomains storage.uniformBucketLevelAccess; do
    gcloud resource-manager org-policies describe $c --project $P --effective --quiet --format=json
  done
done
```

Result, identical for both projects:

| Constraint | Effective value | Meaning |
|---|---|---|
| `storage.publicAccessPrevention` | not enforced (`booleanPolicy: {}`) | `allUsers` read is allowed |
| `iam.allowedPolicyMemberDomains` | `allValues: ALLOW` | no domain-restricted sharing; `allUsers` can be a member |
| `storage.uniformBucketLevelAccess` | enforced | buckets must use uniform access (the plan wants that anyway) |

So the org policy does **not** block public buckets. What blocks the plan as written is an IAM **deny** policy, not an org policy:

```sh
gcloud storage buckets create gs://nivosense-staging --project nivosense --location europe-west1 --uniform-bucket-level-access --quiet
# HTTPError 403: <operator-account> does not have storage.buckets.create access to the Google Cloud project.
# Permission 'storage.buckets.create' denied on resource '//storage.googleapis.com/projects/_/buckets/nivosense-staging' due to an IAM deny policy.

gcloud iam policies list --attachment-point="cloudresourcemanager.googleapis.com%2Fprojects%2Fnivosense" --kind=denypolicies --quiet
# {}   (no deny policy on the project itself)
gcloud iam policies list --attachment-point="cloudresourcemanager.googleapis.com%2Forganizations%2F190458521623" --kind=denypolicies --quiet
# Permission iam.googleapis.com/denypolicies.list denied on resource organizations/190458521623
```

The deny is attached above the project (organisation or folder) and cannot be read with this account. The same refusal applies in `darwin-general-sandbox` and every other Darwin project tried on 2026-11-21, and the account cannot create projects. Coordinator decision (logged in `docs/plan/STATUS.md`, 2026-11-21): no org-policy or deny-policy changes, no workaround, no projects of other organisations. Service accounts and WIF go in project `nivosense`, where Mario is owner and which already holds `nivosense-cogs` and `nivosense-web`; storage goes in the existing bucket `nivosense-cogs` under two prefixes until an admin creates the dedicated buckets (1.9).

Resources left untouched: bucket `nivosense-web`, the existing objects of `nivosense-cogs` (`forecasts/`, `observations/`, `predictions/`, `static/`) and the `sa-run-backend` binding on it, and everything in `darwin-general-sandbox`.

### 1.3 Differences from the T0.2 card and why

| Card | Interim state | Why |
|---|---|---|
| Buckets `nivosense-data` and `nivosense-staging` | Prefixes `prod/` and `staging/` in `nivosense-cogs` | Bucket creation denied (1.2). Moving later is a variable change plus a copy (1.9). |
| `allUsers` object read on the whole bucket | `allUsers` object read on the managed folders `staging/` and `prod/` only | `nivosense-cogs` holds older, non-public objects. Bucket IAM conditions cannot be used with `allUsers`, so public read is granted on managed folders, which carry their own IAM policy. Anything outside the two prefixes stays private (anonymous GET returns 403). |
| Writers: object admin on a bucket | `roles/storage.objectAdmin` on `nivosense-cogs` with an IAM condition per object prefix, plus `roles/storage.objectViewer` conditioned on `resource.type == 'storage.googleapis.com/Bucket'` | Same split as the card, scoped by `resource.name`. Listing objects is checked on the bucket, not on an object, so it needs a bucket-level grant. That grant uses `objectViewer`, whose only permissions GCS checks on the bucket are `objects.list`, `managedFolders.list` and `folders.list` (`objects.get` and `managedFolders.get` are checked on the object or folder, where the condition is false). `objectAdmin` is never granted at bucket level, so its `managedFolders.*` and `multipartUploads.*` permissions do not reach the `prod/` managed folder. The probe asserts this with `testIamPermissions` (1.10). Listing shows object names of the whole bucket; it does not grant reading or writing them. |
| Lifecycle 14 days on `nivosense-staging/_scratch/` | 14 days on `staging/_scratch/` | Same rule, prefixed. |
| CORS on the new buckets | CORS on `nivosense-cogs` | Replaces the earlier `deploy/cors.json` setting (`origin: *`), which no browser code uses: the frontend does not read `nivosense-cogs` today. |

### 1.4 APIs

Enabled on 2026-11-21 (audit log `BatchEnableServices`, 00:41:06Z). `storage.googleapis.com` was already on.

```sh
gcloud services enable iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com --project nivosense
```

### 1.4a Service accounts

```sh
gcloud iam service-accounts create nivosense-gha-staging --project nivosense \
  --display-name "NivoSense GitHub Actions staging writer"
gcloud iam service-accounts create nivosense-gha-prod --project nivosense \
  --display-name "NivoSense GitHub Actions prod writer"
```

No keys exist and none may be created; GitHub Actions authenticates only through WIF. Check:

```sh
for s in staging prod; do
  gcloud iam service-accounts keys list --iam-account nivosense-gha-$s@nivosense.iam.gserviceaccount.com --managed-by=user --project nivosense
done
# Listed 0 items.  (both)
```

### 1.5 Workload Identity Federation

The repository id (`1220180727`) is part of the condition so that a deleted and re-created repo with the same name gets no access. `attribute.repo_ref` joins id and ref, so a single principal set can say "this repo, on `main`".

```sh
gh api repos/mariopeces/NivoSense --jq .id
# 1220180727

gcloud iam workload-identity-pools create github --project nivosense --location global \
  --display-name "GitHub Actions"

gcloud iam workload-identity-pools providers create-oidc nivosense-repo --project nivosense --location global \
  --workload-identity-pool github \
  --display-name "mariopeces/NivoSense" \
  --issuer-uri "https://token.actions.githubusercontent.com" \
  --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_id=assertion.repository_id,attribute.ref=assertion.ref,attribute.repo_ref=assertion.repository_id + '@' + assertion.ref" \
  --attribute-condition "assertion.repository_id == '1220180727' && assertion.repository == 'mariopeces/NivoSense'"
```

Who may impersonate whom:

```sh
# Any ref of the repo -> staging writer
gcloud iam service-accounts add-iam-policy-binding nivosense-gha-staging@nivosense.iam.gserviceaccount.com --project nivosense \
  --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/352045667691/locations/global/workloadIdentityPools/github/attribute.repository_id/1220180727"

# Only refs/heads/main of the repo -> prod writer
gcloud iam service-accounts add-iam-policy-binding nivosense-gha-prod@nivosense.iam.gserviceaccount.com --project nivosense \
  --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/352045667691/locations/global/workloadIdentityPools/github/attribute.repo_ref/1220180727@refs/heads/main"
```

`google-github-actions/auth` with `token_format: access_token` calls `iam.serviceAccounts.getAccessToken`, which `roles/iam.workloadIdentityUser` grants to the federated principal.

### 1.6 Bucket access

```sh
# Object rights, per prefix
gcloud storage buckets add-iam-policy-binding gs://nivosense-cogs \
  --member "serviceAccount:nivosense-gha-staging@nivosense.iam.gserviceaccount.com" \
  --role roles/storage.objectAdmin \
  --condition "title=staging-objects,description=Objects under staging/,expression=resource.name.startsWith('projects/_/buckets/nivosense-cogs/objects/staging/')"

gcloud storage buckets add-iam-policy-binding gs://nivosense-cogs \
  --member "serviceAccount:nivosense-gha-prod@nivosense.iam.gserviceaccount.com" \
  --role roles/storage.objectAdmin \
  --condition "title=staging-and-prod-objects,description=Objects under staging/ or prod/,expression=resource.name.startsWith('projects/_/buckets/nivosense-cogs/objects/staging/') || resource.name.startsWith('projects/_/buckets/nivosense-cogs/objects/prod/')"

# Listing (bucket-level check only)
for s in staging prod; do
  gcloud storage buckets add-iam-policy-binding gs://nivosense-cogs \
    --member "serviceAccount:nivosense-gha-$s@nivosense.iam.gserviceaccount.com" \
    --role roles/storage.objectViewer \
    --condition "title=bucket-listing,description=Bucket-level checks only (objects.list),expression=resource.type == 'storage.googleapis.com/Bucket'"
done

# Public read on the two data prefixes only
gcloud storage managed-folders create gs://nivosense-cogs/staging/ gs://nivosense-cogs/prod/
gcloud storage managed-folders add-iam-policy-binding gs://nivosense-cogs/staging/ --member allUsers --role roles/storage.objectViewer
gcloud storage managed-folders add-iam-policy-binding gs://nivosense-cogs/prod/ --member allUsers --role roles/storage.objectViewer
```

### 1.7 CORS and lifecycle

The files are in `deploy/gcs/`. Origins: the Pages site (`https://mariopeces.github.io`), the staging site (served from `https://storage.googleapis.com/<staging bucket>/<staging prefix>site/`, T0.7) and the Vite dev and preview servers (`http://localhost:5173`, `http://localhost:4173`).

```sh
gcloud storage buckets update gs://nivosense-cogs --cors-file=deploy/gcs/cors.json --lifecycle-file=deploy/gcs/lifecycle.json
```

Uploads must not be gzip-encoded: COGs and PMTiles are read with HTTP ranges, and GCS ignores `Range` on objects stored with `Content-Encoding: gzip` (it decompresses and sends the whole object). Never pass `-z`/`--gzip-in-flight-all`/`--gzip-local-all` to `gcloud storage cp`, and never set `Content-Encoding` on products. The probe asserts that its upload has no `contentEncoding` and that a ranged GET returns `x-goog-stored-content-encoding: identity`.

### 1.8 GitHub repository variables (not secrets)

```sh
R=mariopeces/NivoSense
gh variable set GCP_PROJECT      -R $R --body nivosense
gh variable set GCP_WIF_PROVIDER -R $R --body projects/352045667691/locations/global/workloadIdentityPools/github/providers/nivosense-repo
gh variable set GCP_SA_STAGING   -R $R --body nivosense-gha-staging@nivosense.iam.gserviceaccount.com
gh variable set GCP_SA_PROD      -R $R --body nivosense-gha-prod@nivosense.iam.gserviceaccount.com
gh variable set DATA_BUCKET      -R $R --body nivosense-cogs
gh variable set DATA_PREFIX      -R $R --body prod/
gh variable set STAGING_BUCKET   -R $R --body nivosense-cogs
gh variable set STAGING_PREFIX   -R $R --body staging/
```

### 1.9 Moving to dedicated buckets (needs a Darwin org admin)

To be run by an account not covered by the deny policy (or after an exception for the `nivosense` project). Then the owner of `nivosense` runs the rest.

```sh
# Admin
for b in nivosense-data nivosense-staging; do
  gcloud storage buckets create gs://$b --project nivosense --location europe-west1 \
    --uniform-bucket-level-access
done

# Owner of project nivosense
for b in nivosense-data nivosense-staging; do
  gcloud storage buckets add-iam-policy-binding gs://$b --member allUsers --role roles/storage.objectViewer
  gcloud storage buckets update gs://$b --cors-file=deploy/gcs/cors.json
  gcloud storage buckets add-iam-policy-binding gs://$b \
    --member "serviceAccount:nivosense-gha-prod@nivosense.iam.gserviceaccount.com" --role roles/storage.objectAdmin
done
gcloud storage buckets add-iam-policy-binding gs://nivosense-staging \
  --member "serviceAccount:nivosense-gha-staging@nivosense.iam.gserviceaccount.com" --role roles/storage.objectAdmin
# On the dedicated bucket the scratch prefix is _scratch/ (deploy/gcs/lifecycle-dedicated.json);
# from then on, 1.7 uses that file for nivosense-staging instead of deploy/gcs/lifecycle.json.
gcloud storage buckets update gs://nivosense-staging --lifecycle-file=deploy/gcs/lifecycle-dedicated.json

# Copy the data, keeping metadata (Cache-Control, Content-Type)
gcloud storage rsync -r gs://nivosense-cogs/prod/    gs://nivosense-data/
gcloud storage rsync -r gs://nivosense-cogs/staging/ gs://nivosense-staging/

# Switch the variables
R=mariopeces/NivoSense
gh variable set DATA_BUCKET    -R $R --body nivosense-data
gh variable delete DATA_PREFIX    -R $R   # variables cannot be empty; unset reads as ""
gh variable set STAGING_BUCKET -R $R --body nivosense-staging
gh variable delete STAGING_PREFIX -R $R
```

After the switch, run the storage probe (1.10) on a branch and on `main`, then remove the interim bindings and managed folders from `nivosense-cogs`.

### 1.10 Verifying access

`.github/workflows/storage-probe.yml` runs on any push that changes it and on demand (`workflow_dispatch`, available once the file is on `main`):

- every ref: the staging writer uploads `${STAGING_PREFIX}_scratch/probe/<run>` (must be HTTP 200, no `contentEncoding`), is refused on `${DATA_PREFIX}` (must be HTTP 403), holds only `storage.objects.list` on the bucket and on the `${DATA_PREFIX}` managed folder (`testIamPermissions` over object, managed-folder and multipart permissions), can list its prefix, then an anonymous `OPTIONS` preflight with `Range` and a ranged GET from the Pages origin must give 200 and 206 with `Content-Range` exposed;
- branch refs: impersonating the prod writer must fail;
- `main`: the prod writer uploads to both prefixes (must be HTTP 200 each), then deletes the prod probe (must be HTTP 204; `prod/` has no lifecycle rule);
- a failure on `main` opens an issue "Storage access probe failed on main", or comments on the open one.

```sh
gh workflow run storage-probe.yml -R mariopeces/NivoSense --ref main
gh run list -R mariopeces/NivoSense --workflow storage-probe.yml -L 5
```

Read-only state check:

```sh
gcloud storage buckets describe gs://nivosense-cogs --project nivosense --format=json
gcloud storage buckets get-iam-policy gs://nivosense-cogs --project nivosense --format=json
gcloud storage managed-folders list gs://nivosense-cogs/ --project nivosense
gcloud iam workload-identity-pools providers describe nivosense-repo --workload-identity-pool github --location global --project nivosense
gh variable list -R mariopeces/NivoSense
```

### 1.11 Log of one-off actions

- 2026-11-21: `gcloud storage buckets create gs://nivosense-data` and `gs://nivosense-staging` (`--project nivosense --location europe-west1 --uniform-bucket-level-access`): both refused by the deny policy (1.2). Net change: none.
- 2026-11-21: the WIF provider was created, then updated once (`updateMask: attributeCondition,attributeMapping`) to the values in 1.5. Running the 1.5 command alone reproduces the final state.
- 2026-11-21: one bucket IAM call on `nivosense-cogs` was rejected with `INVALID_ARGUMENT`. Net change: none.
- 2026-11-21: a test object `staging/_scratch/probe/local-check` was uploaded by hand while checking CORS. The 14-day scratch rule deletes it.
- 2026-11-22 (G-Infra round 1, finding F3): the first bucket bindings granted `objectAdmin` with the condition `resource.type == 'storage.googleapis.com/Bucket' || <prefix>`. That gave every `objectAdmin` permission checked on the bucket, including `managedFolders.*` and `multipartUploads.*`, to both writers. They were replaced by the 1.6 bindings: added first, then the old ones removed with
  `gcloud storage buckets remove-iam-policy-binding gs://nivosense-cogs --member "serviceAccount:nivosense-gha-staging@nivosense.iam.gserviceaccount.com" --role roles/storage.objectAdmin --condition "title=staging-prefix,description=Objects under staging/ and listing,expression=resource.type == 'storage.googleapis.com/Bucket' || resource.name.startsWith('projects/_/buckets/nivosense-cogs/objects/staging/')"`
  and
  `gcloud storage buckets remove-iam-policy-binding gs://nivosense-cogs --member "serviceAccount:nivosense-gha-prod@nivosense.iam.gserviceaccount.com" --role roles/storage.objectAdmin --condition "title=staging-and-prod-prefixes,description=Objects under staging/ or prod/ and listing,expression=resource.type == 'storage.googleapis.com/Bucket' || resource.name.startsWith('projects/_/buckets/nivosense-cogs/objects/staging/') || resource.name.startsWith('projects/_/buckets/nivosense-cogs/objects/prod/')"`.
- 2026-11-22: `gcloud services enable policytroubleshooter.googleapis.com --project nivosense`, to check the prod writer's object rights without a run on `main`. The troubleshooter evaluated every `resource.name.startsWith(...)` condition as false, including the staging writer on `staging/`, whose real upload had succeeded, so its output was discarded. Disabled again with `gcloud services disable policytroubleshooter.googleapis.com --project nivosense --quiet`. Net change: none.

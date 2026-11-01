# Hosting Beyond Retrieval

A private deployment for one person, on free infrastructure. The container
is not platform-specific — anything that runs a container and gives it a
writable `/data` will work.

**2 November 2026 correction (rule 7).** This file originally pointed at a
private Hugging Face Space as "the only free option". That stopped being
true at some point after it was written: Hugging Face now requires a PRO
subscription (~US$9/month) to create a Docker (or Gradio) Space on a
personal account, even private, even on the free CPU tier — confirmed
against the Hub's own billing docs and a Hugging Face forum thread the same
day this was caught. **Google Cloud Run** is the instructions below now
lead with: it has a genuinely free always-on allowance (requests, CPU and
memory, scaling to zero when idle) for a container this size, with no
subscription. The Hugging Face path is kept further down for anyone who
already has PRO or prefers that platform.

## Why this shape

The app is two processes: a FastAPI service and a Streamlit page that calls
it. The platform exposes one port, so nginx sits in front and splits by
path — `/auth/` to the API, everything else to the page. Same origin, which
is what lets the `br_session` cookie set by the OAuth callback be read by
the page afterwards. Which port nginx itself listens on is templated at
container start (`$PORT`, defaulting to 7860) rather than fixed, because
Cloud Run assigns its own port per revision and Hugging Face expects 7860 —
see `deploy/nginx.conf`'s own note.

## What it needs

- **~2 GB RAM.** SPECTER2 is a BERT-base model; a free Hugging Face CPU
  Space has 16 GB and Cloud Run is told `--memory 2Gi` explicitly below —
  both are ample.
- **A writable `/data`.** SQLite holds accounts, sign-ins and saved projects.
- **About a minute** to answer the first search after a cold start, while the
  ranking model loads. The page says so itself.

## Before you deploy (either platform)

### 1. Google OAuth

In the Google Cloud console, open the OAuth client this project already uses
and add the deployment's callback to **Authorised redirect URIs**. You will
not know the exact URL until after the first deploy (Cloud Run assigns one;
a Space's is your chosen name) — deploy once first, then come back and add
it. Leave the existing `http://127.0.0.1:8000/auth/google/callback` in place
so the app still runs locally.

**Rotate the client secret** at the same time, and put only the new one into
whichever platform's secret store. The old one has been on a developer
laptop in a `.env` file for months.

### 2. Decide who may sign in

`ALLOWED_EMAILS` is a comma-separated list. Leave it unset and **anyone with
a Google account can sign in and spend your OpenAI and Gemini keys** — the
app will warn about this in the logs at startup. For a private deployment,
set it to your own address and nothing else.

## Deploying to Google Cloud Run (the free path)

Needs the [`gcloud` CLI](https://cloud.google.com/sdk/docs/install), signed
in (`gcloud auth login`), and a GCP project with billing **linked** — Cloud
Run's free allowance still requires a billing account on the project even
though normal use of a private single-user tool like this stays inside it
(per Google's published free tier: 2 million requests, 180,000 vCPU-seconds
and 360,000 GiB-seconds a month, resettable and changeable by Google with
30 days' notice — check
[cloud.google.com/run/pricing](https://cloud.google.com/run/pricing) for
the current figures rather than trusting a number written here).

1. Enable the API once per project:

       gcloud services enable run.googleapis.com

2. First deploy — no secrets yet, just to learn the assigned URL. Cloud
   Build reads the `Dockerfile` at the repository root and builds it for
   you; nothing to build locally.

       gcloud run deploy beyond-retrieval \
         --source . \
         --region us-central1 \
         --allow-unauthenticated \
         --memory 2Gi --cpu 1 \
         --min-instances 0 --max-instances 1 \
         --timeout 900

   `--allow-unauthenticated` is Cloud Run's own gate, separate from this
   app's `ALLOWED_EMAILS` — without it, Cloud Run's IAM blocks every
   request before nginx ever sees one, which is one gate too many for a
   tool that already screens sign-ins itself. `--timeout 900` matches
   nginx's own `proxy_read_timeout`; left at Cloud Run's 300s default, a
   long screening run would be cut off by the platform before nginx would
   ever time it out. `--max-instances 1` bounds concurrency (and spend) for
   a tool one person uses — raise it only if that stops being true.

   The command prints a URL like
   `https://beyond-retrieval-xxxxxxxxxx-uc.a.run.app` — stable for this
   service name and region across future deploys, which is what makes step
   3 a one-time step rather than a recurring one.

3. Add that URL's callback to the OAuth client (step 1 above), rotate the
   secret, then set everything the app needs. Secrets through Secret
   Manager rather than plain env vars, so they never show up in
   `gcloud run services describe` output or deploy logs:

       printf '%s' "<rotated-client-secret>" | gcloud secrets create google-client-secret --data-file=-
       printf '%s' "<openai-key>"            | gcloud secrets create openai-api-key       --data-file=-
       printf '%s' "<gemini-key>"            | gcloud secrets create gemini-api-key       --data-file=-

       gcloud run services update beyond-retrieval --region us-central1 \
         --set-env-vars GOOGLE_CLIENT_ID=<from-google-cloud>,GOOGLE_REDIRECT_URI=https://<your-url>/auth/google/callback,DASHBOARD_URL=https://<your-url>/,ALLOWED_EMAILS=<your-email>,OPENALEX_MAILTO=<your-email>,BUDGET_CEILING_USD=0.50 \
         --set-secrets GOOGLE_CLIENT_SECRET=google-client-secret:latest,OPENAI_API_KEY=openai-api-key:latest,GEMINI_API_KEY=gemini-api-key:latest

   A redeploy picks up code changes without repeating step 3 — re-run the
   `gcloud run deploy` command from step 2; env vars and secrets already set
   on the service carry over.

Same two caveats as the Hugging Face path below apply here too — storage
under `/data` is ephemeral on Cloud Run exactly the way it is on a Space,
and the budget ceiling is per search, not cumulative. See
"The two things this setup does not solve" further down; it was written
once and applies to both platforms rather than being said twice.

## Deploying to a Hugging Face Space (needs PRO)

Kept for anyone who already pays for PRO or prefers Hugging Face's own
tooling. As of 2 November 2026 this needs a
[PRO subscription](https://huggingface.co/docs/hub/en/billing) (~US$9/month)
on the account creating the Space — confirmed via the Hub's own docs and a
[Hugging Face forum thread](https://discuss.huggingface.co/t/docker-sdk-now-marked-as-paid-when-creating-a-new-space/177580)
reporting the same change; it was free when this project's Dockerfile was
first written.

1. Create a Space: SDK **Docker**, visibility **Private**.
2. Push this repository to it (`git remote add space …` then `git push space main`).
   The Space builds the `Dockerfile` at the repository root.
3. Nothing to add: the repository's own `README.md` already carries the
   frontmatter a Space reads (`sdk: docker`, `app_port: 7860`), so the Space
   is configured by the push itself.

4. Set these under **Settings → Variables and secrets**:

   | Name | Kind | Value |
   | --- | --- | --- |
   | `GOOGLE_CLIENT_ID` | secret | from Google Cloud |
   | `GOOGLE_CLIENT_SECRET` | secret | the **rotated** one |
   | `GOOGLE_REDIRECT_URI` | variable | `https://<your-space>.hf.space/auth/google/callback` |
   | `DASHBOARD_URL` | variable | `https://<your-space>.hf.space/` |
   | `OPENAI_API_KEY` | secret | yours |
   | `GEMINI_API_KEY` | secret | yours |
   | `ALLOWED_EMAILS` | variable | your own address |
   | `OPENALEX_MAILTO` | variable | your address — OpenAlex asks callers to identify themselves |
   | `BUDGET_CEILING_USD` | variable | `0.50` (the image default) |

## What has been checked, and what has not

The image has never been built: there is no Docker on the machine this was
written on, so whichever platform you deploy to first will run the first
real build. What *was* checked is the part that usually breaks a first
build — every pin in `requirements-serve.txt` was resolved against
`manylinux_2_28_x86_64` for Python 3.13, including the CPU-only
`torch==2.14.0` wheel and the yanked `google-genai==0.3.0`. All of them have
Linux wheels, which matters because `python:3.13-slim` has no compiler:
anything without one would have been built from source and failed.

That check found one real problem. `pyyaml==6.0.2` has no Linux wheel for
Python 3.13 at all, and would have failed the build; it was in this file as
insurance rather than because anything imports it, so it is gone.

The port-templating added for Cloud Run (2 November 2026) was checked a
different way, since there was still no Docker to build against: the `sed`
substitution was run directly against `deploy/nginx.conf` with `PORT` set
to `8080` and left unset, and both produced a valid `listen` line. That
proves the templating is correct; it does not prove nginx accepts the
templated file inside the real container, which is what the first Cloud Run
deploy will actually test.

## The two things this setup does not solve

**Storage is not persistent, on either platform's free tier.** `/data`
lives inside the container, so a rebuild, a redeploy or (on Cloud Run) a
scale-to-zero cold restart loses saved projects, cached model answers and
your sign-in. Nothing is corrupted — you sign in again and carry on — but
it is not a place to keep work you care about. Persistent storage is a paid
add-on on both platforms (a Space's own volume, or a Cloud Run service
backed by Filestore/Cloud SQL instead of local disk); the lighter
alternative on either is to back the two SQLite files up to a private
dataset repository, or a Cloud Storage bucket, on a timer.

**The spend ceiling is per run, not cumulative.** `BUDGET_CEILING_USD` caps
one search, because a fresh `Meter` is built for each request in
`_suggest_session`. Fifty searches is fifty ceilings. On a private
deployment with an allowlist of one that is a non-issue; if this is ever
opened up, a cumulative cap has to come first.

## Running the container anywhere else

    docker build -t beyond-retrieval .
    docker run -p 7860:7860 --env-file .env -v "$PWD/data:/data" beyond-retrieval

`PORT` defaults to 7860 if the host doesn't set it (add `-e PORT=8080` to
the command above to run on a different one). `GOOGLE_REDIRECT_URI` and
`DASHBOARD_URL` must match whatever address the browser actually reaches,
or sign-in will fail with a redirect-URI mismatch.

# Hosting Beyond Retrieval

A private deployment for one person, on free infrastructure. The container
is not platform-specific — anything that runs a container and gives it a
writable `/data` will work — but these instructions are for a **private
Hugging Face Space**, which is the only free option that has enough memory
for the ranking model and does not charge for a public HTTPS address.

## Why this shape

The app is two processes: a FastAPI service and a Streamlit page that calls
it. A Space exposes one port, so nginx sits on 7860 and splits by path —
`/auth/` to the API, everything else to the page. Same origin, which is what
lets the `br_session` cookie set by the OAuth callback be read by the page
afterwards.

## What it needs

- **~2 GB RAM.** SPECTER2 is a BERT-base model; the free CPU Space has 16 GB,
  which is ample.
- **A writable `/data`.** SQLite holds accounts, sign-ins and saved projects.
- **About a minute** to answer the first search after a cold start, while the
  ranking model loads. The page says so itself.

## Before you deploy

### 1. Google OAuth

In the Google Cloud console, open the OAuth client this project already uses
and add the Space's callback to **Authorised redirect URIs**:

    https://<your-space>.hf.space/auth/google/callback

Leave the existing `http://127.0.0.1:8000/auth/google/callback` in place so
the app still runs locally.

**Rotate the client secret** at the same time, and put only the new one in
the Space's secrets. The old one has been on a developer laptop in a
`.env` file for months.

### 2. Decide who may sign in

`ALLOWED_EMAILS` is a comma-separated list. Leave it unset and **anyone with
a Google account can sign in and spend your OpenAI and Gemini keys** — the
app will warn about this in the logs at startup. For a private deployment,
set it to your own address and nothing else.

## Deploying

1. Create a Space: SDK **Docker**, visibility **Private**.
2. Push this repository to it (`git remote add space …` then `git push space main`).
   The Space builds the `Dockerfile` at the repository root.
3. Add the Space's `README.md` frontmatter so it knows the port:

   ```yaml
   ---
   title: Beyond Retrieval
   sdk: docker
   app_port: 7860
   pinned: false
   ---
   ```

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

## The two things this setup does not solve

**Storage is not persistent on the free tier.** `/data` lives in the
container, so a rebuild or a restart loses saved projects, cached model
answers and your sign-in. Nothing is corrupted — you sign in again and carry
on — but it is not a place to keep work you care about. Persistent storage on
a Space is a paid add-on; the alternative is to back the two SQLite files up
to a private dataset repository on a timer.

**The spend ceiling is per run, not cumulative.** `BUDGET_CEILING_USD` caps
one search, because a fresh `Meter` is built for each request in
`_suggest_session`. Fifty searches is fifty ceilings. On a private
deployment with an allowlist of one that is a non-issue; if this is ever
opened up, a cumulative cap has to come first.

## Running the container anywhere else

    docker build -t beyond-retrieval .
    docker run -p 7860:7860 --env-file .env -v "$PWD/data:/data" beyond-retrieval

`GOOGLE_REDIRECT_URI` and `DASHBOARD_URL` must match whatever address the
browser actually reaches, or sign-in will fail with a redirect-URI mismatch.

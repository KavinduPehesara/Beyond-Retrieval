# Beyond Retrieval, as one container.
#
# Not platform-specific: any host that can run a container and give it a
# writable /data will do. Originally built for a Hugging Face Space (single
# exposed port, 7860); also runs on Google Cloud Run, which assigns its own
# port via $PORT per revision instead. deploy/start.sh templates whichever
# port is given into nginx at boot, so this one image serves both without a
# rebuild -- see deploy/nginx.conf's own note on the same point.
#
# SPECTER2's weights are baked in rather than fetched at boot. They are about
# 440 MB, and downloading them on first request would put that on top of the
# minute the model already takes to load -- which the page itself warns about.
# A bigger image for a faster first search is the right trade on a deployment
# that is woken up, used once, and left alone.

FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/app/.cache/huggingface \
    TRANSFORMERS_VERBOSITY=error \
    TOKENIZERS_PARALLELISM=false

RUN apt-get update \
 && apt-get install -y --no-install-recommends nginx ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only torch. The default wheel carries the CUDA runtime, which is well
# over a gigabyte of driver nobody here can use.
COPY deploy/requirements-serve.txt ./deploy/requirements-serve.txt
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.14.0 \
 && pip install -r deploy/requirements-serve.txt

# Pull the ranking model into the image. Done before the source is copied so
# that editing the app does not re-download 440 MB on every build.
RUN python -c "\
from transformers import AutoTokenizer, AutoModel; \
from adapters import AutoAdapterModel; \
AutoTokenizer.from_pretrained('allenai/specter2_base'); \
m = AutoAdapterModel.from_pretrained('allenai/specter2_base'); \
m.load_adapter('allenai/specter2', source='hf', load_as='proximity', set_active=True); \
print('specter2 cached')"

COPY slr ./slr
COPY app ./app
COPY prompts ./prompts
COPY configs ./configs
COPY deploy ./deploy
# The logo and favicon. The page falls back to a text wordmark without
# these, so a missing copy here would not crash the container -- it would
# just quietly ship an unbranded app, which is worse.
COPY assets ./assets

# The platform runs the container as an unprivileged user, and the model
# cache and app tree have to stay readable to it.
RUN chmod +x deploy/start.sh \
 && mkdir -p /data \
 && chmod -R a+rX /app \
 && chmod a+rwX /data

ENV SLR_PROMPTS_DIR=/app/prompts \
    SLR_DB_PATH=/data/slr.db \
    SLR_LIVE_DB_PATH=/data/live_reviews.sqlite3 \
    SLR_RUNS_DIR=/data/runs \
    SLR_API_URL=http://127.0.0.1:8000 \
    BUDGET_CEILING_USD=0.50

# Documentation only -- EXPOSE does not bind a port, and Cloud Run ignores
# it in favour of $PORT. Still 7860 so a plain `docker run -p 7860:7860`
# and a Hugging Face Space both work with no extra flags.
EXPOSE 7860

CMD ["./deploy/start.sh"]

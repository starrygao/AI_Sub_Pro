FROM node:22-bookworm-slim AS codex
RUN npm install --prefix /opt/codex @openai/codex@0.155.1

FROM python:3.12-slim-bookworm
ARG DEBIAN_MIRROR=https://mirrors.tuna.tsinghua.edu.cn
RUN sed -i "s|http://deb.debian.org|${DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources && apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update && apt-get install -y --no-install-recommends ffmpeg util-linux libgomp1 ca-certificates git && rm -rf /var/lib/apt/lists/*
COPY --from=codex /usr/local/bin/node /usr/local/bin/node
COPY --from=codex /opt/codex /opt/codex
RUN ln -s /opt/codex/node_modules/.bin/codex /usr/local/bin/codex
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt 'faster-whisper==1.2.1'
COPY app /app/app
RUN chmod -R a+rX /app/app
COPY deploy/docker/entrypoint.py /app/entrypoint.py
ENV AI_SUB_PRO_DATA_DIR=/data AISUBPRO_LIBRARY_CONFIG=/config/library.json CODEX_HOME=/codex \
    HF_HOME=/models HF_HUB_DISABLE_TELEMETRY=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
    AISUBPRO_ASR_CPU_THREADS=1 AISUBPRO_FFMPEG=/usr/bin/ffmpeg AISUBPRO_FFPROBE=/usr/bin/ffprobe \
    PYTHONUNBUFFERED=1
EXPOSE 18091
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s CMD python -c "import urllib.request,os; urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://'+os.environ.get('AISUBPRO_SERVER_HOST','127.0.0.1')+':'+os.environ.get('AISUBPRO_SERVER_PORT','18091')+'/healthz',timeout=3)"
ENTRYPOINT ["ionice","-c","3","nice","-n","19","python","/app/entrypoint.py"]

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        git \
        gzip \
        jq \
        libgomp1 \
        libtbb12 \
        python3 \
        python3-pip \
        python3-venv \
        tar \
        tzdata \
        unzip \
        util-linux \
        fonts-liberation \
        fonts-noto-cjk \
        libasound2 \
        libatk-bridge2.0-0 \
        libatk1.0-0 \
        libcairo2 \
        libcups2 \
        libdbus-1-3 \
        libdrm2 \
        libgbm1 \
        libgl1 \
        libglib2.0-0 \
        libgtk-3-0 \
        libicu70 \
        libnspr4 \
        libnss3 \
        libpango-1.0-0 \
        libx11-6 \
        libxcb1 \
        libxcomposite1 \
        libxdamage1 \
        libxext6 \
        libxfixes3 \
        libxkbcommon0 \
        libxrandr2 \
        libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

# Pre-download PaddlePaddle + PaddleOCR runtime dependencies and models
RUN python3 -m venv /tmp/build-venv \
    && /tmp/build-venv/bin/pip install --quiet --no-cache-dir \
        paddlepaddle==3.2.0 paddleocr==3.3.3 \
    && /tmp/build-venv/bin/python -c "import paddle; print('[PASS] PaddlePaddle imported successfully')" \
    && printf '%s\n' \
        'from paddleocr import PaddleOCR' \
        'PaddleOCR(lang="ch", ocr_version="PP-OCRv5", use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False)' \
        'print("[PASS] PaddleOCR models downloaded")' \
        > /tmp/warmup.py \
    && PADDLE_PDX_CACHE_HOME=/opt/paddlex-models /tmp/build-venv/bin/python /tmp/warmup.py \
    && rm -f /tmp/warmup.py \
    && rm -rf /tmp/build-venv

# Pre-download CloakBrowser Chromium binary (using curl + system tar to
# avoid Python tarfile glibc heap corruption on 206 MB archives)
RUN set -eux \
    && curl -fsSL 'https://cloakbrowser.dev/chromium-v146.0.7680.177.5/cloakbrowser-linux-x64.tar.gz' \
        -o /tmp/cloakbrowser.tar.gz \
    && mkdir -p /opt/cloakbrowser \
    && tar xzf /tmp/cloakbrowser.tar.gz -C /opt/cloakbrowser \
    && rm -f /tmp/cloakbrowser.tar.gz \
    && chmod +x /opt/cloakbrowser/chrome \
    && /opt/cloakbrowser/chrome --version \
    && echo '[PASS] CloakBrowser Chromium downloaded and verified'

RUN useradd --create-home --shell /bin/bash runner \
    && mkdir -p /runner-data/actions-runner /runner-data/_work /runner-data/home /runner-data/venv \
    && chown -R runner:runner /runner-data /home/runner

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /runner-data

ENTRYPOINT ["/entrypoint.sh"]

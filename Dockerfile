FROM python:3.13-slim

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends zip && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY src/requirements.txt .
# pip is build-only tooling: `--target .` copies project deps into /build but never pip
# itself, so it doesn't reach out.zip. Remove it (and its dist-info) right after use so
# CVEs in pip's own vendored libs (e.g. msgpack, setuptools) don't show up in the image scan.
RUN pip install --no-cache-dir -r requirements.txt --target . && \
    rm -rf /usr/local/lib/python3.13/site-packages/pip \
           /usr/local/lib/python3.13/site-packages/pip-*.dist-info
COPY src .
RUN zip -r /out.zip .

CMD ["/bin/sh"]

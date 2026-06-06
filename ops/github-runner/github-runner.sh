#!/usr/bin/env bash
set -euo pipefail

RUNNER_NAME="${RUNNER_NAME:-oilprice-github-runner}"
IMAGE_NAME="${IMAGE_NAME:-oilprice-github-runner:latest}"
DATA_DIR="${DATA_DIR:-/docker/oilprice/github-runner}"
GH_REPOSITORY_URL="${GH_REPOSITORY_URL:-https://github.com/luckkyboy/chinese-oil-price-data}"
GH_RUNNER_TOKEN="${GH_RUNNER_TOKEN:-${1:-}}"
GH_RUNNER_LABELS="${GH_RUNNER_LABELS:-oilprice}"
RUNNER_VERSION="${RUNNER_VERSION:-2.334.0}"

if [ -z "${GH_RUNNER_TOKEN}" ]; then
  echo "Usage: $0 <github-runner-token>" >&2
  echo "Or set GH_RUNNER_TOKEN in the environment." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "${DATA_DIR}"

docker build -t "${IMAGE_NAME}" "${SCRIPT_DIR}"

docker rm -f "${RUNNER_NAME}" 2>/dev/null || true
docker run -d --restart unless-stopped --name "${RUNNER_NAME}" \
  -v "${DATA_DIR}:/runner-data" \
  --shm-size 500m \
  --add-host host.docker.internal:host-gateway \
  -e GH_REPOSITORY_URL="${GH_REPOSITORY_URL}" \
  -e GH_RUNNER_TOKEN="${GH_RUNNER_TOKEN}" \
  -e GH_RUNNER_NAME="${RUNNER_NAME}" \
  -e GH_RUNNER_LABELS="${GH_RUNNER_LABELS}" \
  -e RUNNER_VERSION="${RUNNER_VERSION}" \
  -e TZ=Asia/Shanghai \
  -e DISABLE_MODEL_SOURCE_CHECK=True \
  "${IMAGE_NAME}"

echo "Started ${RUNNER_NAME}"
echo "Logs: docker logs -f ${RUNNER_NAME}"

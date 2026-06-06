#!/usr/bin/env bash
set -euo pipefail

RUNNER_VERSION="${RUNNER_VERSION:-2.334.0}"
RUNNER_ARCH="${RUNNER_ARCH:-x64}"
DATA_ROOT="${DATA_ROOT:-/runner-data}"
RUNNER_ROOT="${RUNNER_ROOT:-${DATA_ROOT}/actions-runner}"
RUNNER_WORKDIR="${GH_RUNNER_WORKDIR:-${DATA_ROOT}/_work}"
RUNNER_LABELS="${GH_RUNNER_LABELS:-oilprice}"
RUNNER_NAME="${GH_RUNNER_NAME:-oilprice-$(hostname)}"
VENV_DIR="${VENV_DIR:-${DATA_ROOT}/venv}"

if [ "$(id -u)" = "0" ]; then
  mkdir -p "${DATA_ROOT}/actions-runner" "${DATA_ROOT}/_work" "${DATA_ROOT}/home" "${DATA_ROOT}/venv" "${DATA_ROOT}/binary"
  # Pre-downloaded build artifacts — only copy if missing from persistent volume
  if [ -d /opt/cloakbrowser ] && [ ! -f "${DATA_ROOT}/binary/cloakbrowser/chrome" ]; then
    cp -a /opt/cloakbrowser "${DATA_ROOT}/binary/cloakbrowser"
    # Create stable symlink so CLOAKBROWSER_BINARY_PATH always works
    CHROME_BIN=$(find "${DATA_ROOT}/binary/cloakbrowser" -name chrome -type f | head -1)
    if [ -n "$CHROME_BIN" ]; then
      ln -sf "$CHROME_BIN" "${DATA_ROOT}/binary/cloakbrowser/chrome"
      echo "Copied CloakBrowser Chromium (symlinked to ${CHROME_BIN})"
    fi
  fi
  if [ -d /opt/paddlex-models ] && [ ! -d "${DATA_ROOT}/binary/paddlex-models" ]; then
    cp -a /opt/paddlex-models "${DATA_ROOT}/binary/paddlex-models"
    echo "Copied PaddleOCR models to ${DATA_ROOT}/binary/paddlex-models"
  fi
  chown -R runner:runner "${DATA_ROOT}"
  exec runuser -u runner -- "$0" "$@"
fi

if [ -z "${GH_REPOSITORY_URL:-}" ]; then
  echo "GH_REPOSITORY_URL is required, for example https://github.com/OWNER/chinese-oil-price-data" >&2
  exit 1
fi

mkdir -p "${RUNNER_ROOT}" "${RUNNER_WORKDIR}" "${DATA_ROOT}/home" "${VENV_DIR}"
export HOME="${DATA_ROOT}/home"

if [ ! -x "${VENV_DIR}/bin/python" ]; then
  python3 -m venv "${VENV_DIR}"
fi
export PATH="${VENV_DIR}/bin:${PATH}"
python -m pip install --upgrade pip setuptools wheel

cd "${RUNNER_ROOT}"

if [ ! -x "${RUNNER_ROOT}/config.sh" ]; then
  runner_tar="actions-runner-linux-${RUNNER_ARCH}-${RUNNER_VERSION}.tar.gz"
  runner_url="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${runner_tar}"
  echo "Downloading GitHub Actions runner ${RUNNER_VERSION} from ${runner_url}"
  curl -fsSL "${runner_url}" -o "/tmp/${runner_tar}"
  tar xzf "/tmp/${runner_tar}" -C "${RUNNER_ROOT}"
  rm -f "/tmp/${runner_tar}"
fi

if [ ! -f "${RUNNER_ROOT}/.runner" ]; then
  if [ -z "${GH_RUNNER_TOKEN:-}" ]; then
    echo "GH_RUNNER_TOKEN is required for first-time runner registration." >&2
    echo "Create one in GitHub: Settings -> Actions -> Runners -> New self-hosted runner." >&2
    exit 1
  fi
  "${RUNNER_ROOT}/config.sh" \
    --url "${GH_REPOSITORY_URL}" \
    --token "${GH_RUNNER_TOKEN}" \
    --name "${RUNNER_NAME}" \
    --labels "${RUNNER_LABELS}" \
    --work "${RUNNER_WORKDIR}" \
    --unattended \
    --replace
fi

exec "${RUNNER_ROOT}/run.sh"

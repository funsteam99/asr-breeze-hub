#!/usr/bin/env bash
# Put a Breeze ASR ggml model in place.
#
# Deliberately does not hard-code a download URL. The `ggml-breeze-asr-26.bin`
# in use on the reference machine was converted locally, and inventing a
# plausible-looking Hugging Face link that 404s is worse than saying so. Set
# MODEL_URL in .env, or pass a local path:
#
#     scripts/fetch_model.sh /path/to/ggml-breeze-asr-26.bin

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "${REPO_ROOT}/.env" ] && set -a && . "${REPO_ROOT}/.env" && set +a

MODEL_PATH="${MODEL_PATH:-${REPO_ROOT}/models/ggml-breeze-asr-26.bin}"
case "${MODEL_PATH}" in
  /*) ;;
  *) MODEL_PATH="${REPO_ROOT}/${MODEL_PATH}" ;;
esac
MODEL_URL="${MODEL_URL:-}"
MODEL_SHA256="${MODEL_SHA256:-}"
SOURCE="${1:-}"

mkdir -p "$(dirname "${MODEL_PATH}")"

verify() {
  [ -z "${MODEL_SHA256}" ] && return 0
  command -v sha256sum >/dev/null 2>&1 || { echo "  sha256sum unavailable, skipping checksum"; return 0; }
  echo "  verifying checksum"
  local actual
  actual="$(sha256sum "${MODEL_PATH}" | awk '{print $1}')"
  if [ "${actual}" != "${MODEL_SHA256}" ]; then
    echo "checksum mismatch:" >&2
    echo "  expected ${MODEL_SHA256}" >&2
    echo "  actual   ${actual}" >&2
    exit 1
  fi
}

if [ -f "${MODEL_PATH}" ] && [ -z "${SOURCE}" ]; then
  SIZE="$(du -h "${MODEL_PATH}" | awk '{print $1}')"
  echo "==> Model already present: ${MODEL_PATH} (${SIZE})"
  verify
  exit 0
fi

if [ -n "${SOURCE}" ]; then
  echo "==> Copying model from ${SOURCE}"
  cp "${SOURCE}" "${MODEL_PATH}"
elif [ -n "${MODEL_URL}" ]; then
  echo "==> Downloading model from ${MODEL_URL}"
  if command -v curl >/dev/null 2>&1; then
    curl -fL --progress-bar -o "${MODEL_PATH}.part" "${MODEL_URL}"
  elif command -v wget >/dev/null 2>&1; then
    wget -O "${MODEL_PATH}.part" "${MODEL_URL}"
  else
    echo "neither curl nor wget is available" >&2
    exit 1
  fi
  mv "${MODEL_PATH}.part" "${MODEL_PATH}"
else
  cat >&2 <<EOF

No model available and no source given.

  expected at : ${MODEL_PATH}

Provide one of:
  1. a local file   ->  scripts/fetch_model.sh /path/to/ggml-breeze-asr-26.bin
  2. a download URL ->  set MODEL_URL= in .env, then re-run

Any whisper.cpp-compatible ggml model works; Breeze ASR is simply the one tuned
for Taiwanese-accented Mandarin. For a quick smoke test you can point MODEL_PATH
at a stock model from whisper.cpp's models/download-ggml-model.sh instead.

EOF
  exit 2
fi

verify
echo "==> Model ready: ${MODEL_PATH} ($(du -h "${MODEL_PATH}" | awk '{print $1}'))"

#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/shorts-factory"
APP_USER="shorts-factory"
SWAP_FILE="/swapfile"
SWAP_SIZE_MIB=2048

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this installer as root" >&2
  exit 1
fi

for required in pyproject.toml config.toml .env client_secret.json youtube_token.json; do
  if [[ ! -f "${APP_DIR}/${required}" ]]; then
    echo "Missing ${APP_DIR}/${required}" >&2
    exit 1
  fi
done

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates ffmpeg fonts-dejavu-core python3 python3-pip python3-venv util-linux

# FFmpeg and Python can briefly exceed 2 GiB while rendering. Add a small,
# persistent swap file only when the server does not already have swap.
if [[ "$(swapon --noheadings --show | wc -l)" -eq 0 ]]; then
  if [[ ! -f "${SWAP_FILE}" ]]; then
    fallocate -l "${SWAP_SIZE_MIB}M" "${SWAP_FILE}" || \
      dd if=/dev/zero of="${SWAP_FILE}" bs=1M count="${SWAP_SIZE_MIB}" status=progress
  fi
  chmod 600 "${SWAP_FILE}"
  mkswap "${SWAP_FILE}"
  swapon "${SWAP_FILE}"
  if ! grep -qF "${SWAP_FILE} none swap sw 0 0" /etc/fstab; then
    printf '%s\n' "${SWAP_FILE} none swap sw 0 0" >> /etc/fstab
  fi
fi

if ! id "${APP_USER}" >/dev/null 2>&1; then
  useradd --system --home-dir "${APP_DIR}" --shell /usr/sbin/nologin "${APP_USER}"
fi

python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/python" -m pip install --upgrade pip
"${APP_DIR}/.venv/bin/python" -m pip install -e "${APP_DIR}"

install -d -o "${APP_USER}" -g "${APP_USER}" "${APP_DIR}/data" "${APP_DIR}/output"
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"
# Archives created on Windows can preserve source directories as 0500.  The
# service account then owns the files but cannot traverse the Python package,
# which makes every timer run fail with ModuleNotFoundError.  Normalize only
# application code/assets here; secrets below remain locked to 0600.
find "${APP_DIR}/src" -type d -exec chmod 0755 {} +
find "${APP_DIR}/src" -type f -exec chmod 0644 {} +
if [[ -d "${APP_DIR}/assets" ]]; then
  find "${APP_DIR}/assets" -type d -exec chmod 0755 {} +
  find "${APP_DIR}/assets" -type f -exec chmod 0644 {} +
fi
chmod 600 \
  "${APP_DIR}/.env" \
  "${APP_DIR}/config.toml" \
  "${APP_DIR}/client_secret.json" \
  "${APP_DIR}/youtube_token.json"

install -o root -g root -m 0644 \
  "${APP_DIR}/deploy/shorts-factory.service" \
  /etc/systemd/system/shorts-factory.service
install -o root -g root -m 0644 \
  "${APP_DIR}/deploy/shorts-factory.timer" \
  /etc/systemd/system/shorts-factory.timer

systemctl daemon-reload
systemctl enable --now shorts-factory.timer

runuser -u "${APP_USER}" -- \
  "${APP_DIR}/.venv/bin/shorts-factory" --config "${APP_DIR}/config.toml" doctor
systemctl list-timers shorts-factory.timer --no-pager

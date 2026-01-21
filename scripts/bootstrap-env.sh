#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_ENV="${ROOT_DIR}/.env.example"
ROOT_ENV="${ROOT_DIR}/.env"
INFRA_ENV="${ROOT_DIR}/infra/.env"

if [[ ! -f "${SOURCE_ENV}" ]]; then
  echo "Missing ${SOURCE_ENV}. Aborting." >&2
  exit 1
fi

force="${FORCE_ENV:-0}"

ensure_env() {
  local target="$1"
  if [[ -f "${target}" && "${force}" != "1" ]]; then
    echo "Skipping ${target} (already exists)."
    return
  fi

  cp "${SOURCE_ENV}" "${target}"

  if ! grep -q "^BACKEND_PORT=" "${target}"; then
    echo "BACKEND_PORT=19081" >> "${target}"
  fi
  if ! grep -q "^FRONTEND_PORT=" "${target}"; then
    echo "FRONTEND_PORT=19080" >> "${target}"
  fi
  if ! grep -q "^OLLAMA_PORT=" "${target}"; then
    echo "OLLAMA_PORT=11434" >> "${target}"
  fi

  local backend_port
  backend_port="$(grep -m 1 "^BACKEND_PORT=" "${target}" | cut -d= -f2-)"
  if ! grep -q "^NEXT_PUBLIC_BACKEND_URL=" "${target}"; then
    echo "NEXT_PUBLIC_BACKEND_URL=http://localhost:${backend_port}" >> "${target}"
  else
    local current_url
    current_url="$(grep -m 1 "^NEXT_PUBLIC_BACKEND_URL=" "${target}" | cut -d= -f2-)"
    if [[ -z "${current_url}" ]]; then
      echo "NEXT_PUBLIC_BACKEND_URL=http://localhost:${backend_port}" >> "${target}"
    fi
  fi

  if ! grep -q "^NEXT_PUBLIC_BACKEND_PORT=" "${target}"; then
    echo "NEXT_PUBLIC_BACKEND_PORT=${backend_port}" >> "${target}"
  fi

  echo "Generated ${target}."
}

ensure_env "${ROOT_ENV}"
ensure_env "${INFRA_ENV}"

#!/usr/bin/env bash
# Remove local build artifacts.
#
# Usage:
#   ./packaging/clean.sh           # dist, build, nfpm root, build venv, egg-info, caches
#   ./packaging/clean.sh docker    # also remove local webmodbusterm images
#   ./packaging/clean.sh all       # everything above
#
# Env:
#   DOCKER_CMD   Override docker binary, e.g. DOCKER_CMD='sudo docker'

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

TARGET="${1:-default}"

run() {
  echo "+ $*"
  "$@"
}

rm_path() {
  local p="$1"
  if [[ -e "${p}" ]]; then
    echo "removing ${p}"
    rm -rf "${p}"
  fi
}

clean_files() {
  rm_path "${ROOT}/dist"
  rm_path "${ROOT}/build"
  rm_path "${ROOT}/packaging/root"
  rm_path "${ROOT}/.venv-build"
  rm_path "${ROOT}/docs/_gif_frames"

  local egg
  while IFS= read -r -d '' egg; do
    echo "removing ${egg}"
    rm -rf "${egg}"
  done < <(find "${ROOT}" -maxdepth 2 -type d -name '*.egg-info' -print0 2>/dev/null || true)

  # Bytecode caches under the package / packaging (not .venv)
  find "${ROOT}/webmodbusterm" "${ROOT}/packaging" "${ROOT}/deploy" \
    -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
  find "${ROOT}/webmodbusterm" "${ROOT}/packaging" "${ROOT}/deploy" \
    -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete 2>/dev/null || true
}

resolve_docker() {
  if [[ -n "${DOCKER_CMD:-}" ]]; then
    # shellcheck disable=SC2206
    DOCKER_ARGS=(${DOCKER_CMD})
    return 0
  fi
  if ! command -v docker >/dev/null 2>&1; then
    echo "docker not found — skip image cleanup"
    return 1
  fi
  if docker info >/dev/null 2>&1; then
    DOCKER_ARGS=(docker)
    return 0
  fi
  if command -v sudo >/dev/null 2>&1 && sudo -n docker info >/dev/null 2>&1; then
    DOCKER_ARGS=(sudo docker)
    return 0
  fi
  echo "docker not usable (permission?) — skip image cleanup"
  echo "  tip: DOCKER_CMD='sudo docker' ./packaging/clean.sh docker"
  return 1
}

clean_docker() {
  resolve_docker || return 0
  local ids
  ids="$("${DOCKER_ARGS[@]}" images -q 'webmodbusterm' 2>/dev/null || true)"
  if [[ -z "${ids}" ]]; then
    echo "no local webmodbusterm docker images"
    return 0
  fi
  # Remove containers using those images first
  local cids
  cids="$("${DOCKER_ARGS[@]}" ps -aq --filter ancestor=webmodbusterm 2>/dev/null || true)"
  if [[ -n "${cids}" ]]; then
    # shellcheck disable=SC2086
    run "${DOCKER_ARGS[@]}" rm -f ${cids}
  fi
  # shellcheck disable=SC2086
  run "${DOCKER_ARGS[@]}" rmi -f ${ids} || true
}

case "${TARGET}" in
  default|files)
    clean_files
    ;;
  docker)
    clean_files
    clean_docker
    ;;
  all)
    clean_files
    clean_docker
    ;;
  -h|--help|help)
    sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
  *)
    echo "! unknown target: ${TARGET} (use: default|docker|all)" >&2
    exit 1
    ;;
esac

echo "Clean done."

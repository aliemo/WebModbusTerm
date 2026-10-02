#!/usr/bin/env bash
# Local artifact builder (no PyPI / ghcr publish).
#
# Usage:
#   ./packaging/build.sh           # pip + docker
#   ./packaging/build.sh pip
#   ./packaging/build.sh docker
#   ./packaging/build.sh nfpm
#   ./packaging/build.sh all
#
# Env:
#   DOCKER_CMD   e.g. DOCKER_CMD='sudo docker'
#   PYTHON       default: python3

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

DIST="${ROOT}/dist"
STAGE="${ROOT}/packaging/root"
BUILD_VENV="${ROOT}/.venv-build"
VERSION="$(tr -d '[:space:]' < VERSION)"
PYTHON="${PYTHON:-python3}"
TARGET="${1:-default}"
export VERSION

run() {
  echo "+ $*"
  "$@"
}

die() {
  echo "! $*" >&2
  exit 1
}

need() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

ensure_build_venv() {
  need "${PYTHON}"
  if [[ ! -x "${BUILD_VENV}/bin/python" ]]; then
    echo "Creating ${BUILD_VENV} (PEP 668-safe)..."
    if command -v uv >/dev/null 2>&1; then
      run uv venv "${BUILD_VENV}"
    elif "${PYTHON}" -c "import ensurepip" >/dev/null 2>&1; then
      run "${PYTHON}" -m venv "${BUILD_VENV}"
    else
      die "cannot create venv — install python3-venv or uv"
    fi
  fi
  if command -v uv >/dev/null 2>&1; then
    run uv pip install --python "${BUILD_VENV}/bin/python" build
  else
    run "${BUILD_VENV}/bin/pip" install --upgrade pip build
  fi
}

build_pip() {
  ensure_build_venv || return 1
  mkdir -p "${DIST}"
  find "${DIST}" -maxdepth 1 -name 'webmodbusterm-*' -type f -delete 2>/dev/null || true
  run "${BUILD_VENV}/bin/python" -m build --outdir "${DIST}" || return 1
  local whl sdist
  whl="$(find "${DIST}" -maxdepth 1 -name 'webmodbusterm-*-py3-none-any.whl' | head -n1 || true)"
  sdist="$(find "${DIST}" -maxdepth 1 -name 'webmodbusterm-*.tar.gz' | head -n1 || true)"
  [[ -n "${whl}" && -n "${sdist}" ]] || return 1
  echo "pip artifacts:"
  ls -lh "${whl}" "${sdist}"
}

resolve_docker() {
  if [[ -n "${DOCKER_CMD:-}" ]]; then
    # shellcheck disable=SC2206
    DOCKER_ARGS=(${DOCKER_CMD})
    return 0
  fi
  need docker
  if docker info >/dev/null 2>&1; then
    DOCKER_ARGS=(docker)
    return 0
  fi
  if command -v sudo >/dev/null 2>&1 && sudo -n docker info >/dev/null 2>&1; then
    echo "docker socket not writable; using sudo docker"
    DOCKER_ARGS=(sudo docker)
    return 0
  fi
  cat >&2 <<EOF
docker cannot reach the daemon (permission denied?).
  sudo usermod -aG docker "\$USER" && newgrp docker
  DOCKER_CMD='sudo docker' ./packaging/build.sh docker
EOF
  return 1
}

build_docker() {
  resolve_docker || return 1
  local tag="webmodbusterm:${VERSION}"
  run "${DOCKER_ARGS[@]}" build -t "${tag}" -t webmodbusterm:latest . || return 1
  echo "docker image: ${tag} (and webmodbusterm:latest)"
}

create_stage_venv() {
  if command -v uv >/dev/null 2>&1; then
    uv venv .venv
  elif python3 -c "import ensurepip" >/dev/null 2>&1; then
    python3 -m venv .venv
  elif command -v virtualenv >/dev/null 2>&1; then
    virtualenv .venv
  else
    die "cannot create venv — sudo apt install -y python3-venv python3-pip"
  fi
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python .venv/bin/python --upgrade pip
    uv pip install --python .venv/bin/python .
  else
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install .
  fi
}

# Internal: prepare packaging/root for nfpm (not a separate user script).
stage_for_nfpm() {
  need rsync
  need python3
  local prefix="${STAGE}/opt/webmodbusterm"
  local bin="${STAGE}/usr/local/bin"
  rm -rf "${STAGE}"
  mkdir -p "${prefix}" "${bin}"

  rsync -a \
    --exclude '.venv' \
    --exclude '.venv-build' \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude 'packaging' \
    --exclude 'docs' \
    --exclude 'dist' \
    --exclude 'build' \
    --exclude '*.egg-info' \
    "${ROOT}/" "${prefix}/"

  # Keep deploy scripts + service unit
  mkdir -p "${prefix}/deploy"
  rsync -a "${ROOT}/deploy/" "${prefix}/deploy/"

  (
    cd "${prefix}"
    create_stage_venv
  )

  cat > "${bin}/webmodbusterm" <<'EOF'
#!/usr/bin/env bash
export WEBMODBUSTERM_HOME="/opt/webmodbusterm"
exec /opt/webmodbusterm/deploy/webmodbusterm "$@"
EOF
  chmod +x "${bin}/webmodbusterm" "${prefix}/deploy/webmodbusterm" "${prefix}/deploy/install.sh"
  echo "staged ${STAGE}"
}

build_nfpm() {
  need nfpm
  stage_for_nfpm || return 1
  mkdir -p "${DIST}"
  local fmt
  for fmt in deb rpm; do
    run nfpm package -p "${fmt}" -f packaging/nfpm.yaml -t "${DIST}" || return 1
  done
  echo "nfpm packages:"
  ls -lh "${DIST}"/webmodbusterm*.deb "${DIST}"/webmodbusterm*.rpm 2>/dev/null || true
}

case "${TARGET}" in
  default) targets=(pip docker) ;;
  all) targets=(pip docker nfpm) ;;
  pip|docker|nfpm) targets=("${TARGET}") ;;
  -h|--help|help)
    sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
  *)
    die "unknown target: ${TARGET} (pip|docker|nfpm|all)"
    ;;
esac

errors=()
for t in "${targets[@]}"; do
  echo "========== ${t} =========="
  if ! "build_${t}"; then
    errors+=("${t}")
  fi
done

if ((${#errors[@]})); then
  echo "Failed: ${errors[*]}" >&2
  exit 1
fi
echo "Done."

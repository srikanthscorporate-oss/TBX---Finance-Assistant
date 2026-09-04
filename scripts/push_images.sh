#!/usr/bin/env bash
# Tag and push both application images to Docker Hub.
#
#   docker login -u srikanthsdocker      # once, interactively
#   ./scripts/push_images.sh             # tags <sha> and latest, pushes both
#
# Tags are applied by image ID so they work under Docker Desktop's containerd
# image store, and the quoting avoids the zsh ":l" modifier trap.
set -euo pipefail
NS="${DOCKER_NAMESPACE:-srikanthsdocker}"
SHA="$(git rev-parse --short HEAD 2>/dev/null || echo manual)"

for svc in api web; do
  id="$(docker images -q "tbx-${svc}:dev" | head -1)"
  [ -n "$id" ] || { echo "image tbx-${svc}:dev not built; run: docker compose build ${svc}" >&2; exit 1; }
  docker tag "$id" "${NS}/tbx-${svc}:${SHA}"
  docker tag "$id" "${NS}/tbx-${svc}:latest"
  echo "==> pushing ${NS}/tbx-${svc}:{${SHA},latest}"
  docker push "${NS}/tbx-${svc}:${SHA}"
  docker push "${NS}/tbx-${svc}:latest"
done
echo "==> done. Pull with:"
echo "    docker pull ${NS}/tbx-api:latest && docker pull ${NS}/tbx-web:latest"

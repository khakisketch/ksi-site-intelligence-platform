#!/usr/bin/env bash
set -euo pipefail
if rg -n --hidden --glob '!.git/**' \
  'references[./]repos|ksi[_-](platform|terra|scout)' \
  apps services edge workers packages 2>/dev/null; then
  echo "Potential runtime dependency on reference repositories detected." >&2
  exit 1
fi
echo "No direct reference imports detected."

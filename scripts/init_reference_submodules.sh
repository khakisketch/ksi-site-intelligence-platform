#!/usr/bin/env bash
set -euo pipefail
mkdir -p references/repos
git submodule add https://github.com/khakisketch/ksi-platform references/repos/ksi-platform
git submodule add https://github.com/khakisketch/KSI-Terra references/repos/ksi-terra
git submodule add https://github.com/khakisketch/KSI-Scout references/repos/ksi-scout

git -C references/repos/ksi-platform checkout 030ebd5a7ff0762e729b29fe7710f8f3a30e8604
git -C references/repos/ksi-terra checkout 8d62cd38cb627af5c7f1c108537fc5dda89ca103
git -C references/repos/ksi-scout checkout 42ccc0db9a274db94746284bdfbf73db847f5afd

git add .gitmodules references/repos references/REFERENCE_REPOS_LOCK.yaml
echo "Reference submodules added and pinned. Review before commit."

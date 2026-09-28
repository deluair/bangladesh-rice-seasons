#!/usr/bin/env bash
# Download the Singha et al. (2019) 2017 seasonal rice rasters (figshare article 7873157,
# CC BY 4.0) and verify their sha256.
set -euo pipefail
dest="${1:-labels_raw}"
mkdir -p "$dest"
cd "$dest"
while read -r season file_id sha; do
  f="${season}_BGD_2017_V1.tif"
  [ -f "$f" ] || curl -sSL -o "$f" "https://ndownloader.figshare.com/files/${file_id}"
  echo "${sha}  ${f}" | sha256sum -c
done <<'EOF'
Aus 14658821 857f9cc5b00aea00f18dffd1f9ef5eb299fcf31b05a5df0574fb5466812d7935
Aman 14658812 2b110053eb4f84d262c12c9512878b15b2b56bd9e4cc9fcd55ad53d6297f8469
Boro 14658833 bc564accee7bd35023d8960348fa80cb47bcc7d63bb7c9fdb3141a9db8822e14
EOF

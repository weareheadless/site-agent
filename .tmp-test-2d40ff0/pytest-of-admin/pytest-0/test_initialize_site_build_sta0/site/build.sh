#!/usr/bin/env bash
set -euo pipefail
rm -rf output
pelican content -o output -s pelicanconf.py

# output/ is the public boundary; remove accidental source/template copies
# rather than failing a customer deployment.
for forbidden in content themes pelicanconf.py build.sh requirements.txt; do
  if [ -e "output/$forbidden" ]; then
    printf 'public output guard: removed forbidden path: output/%s\n' "$forbidden" >&2
    rm -rf "output/$forbidden"
  fi
done
for relative in index.html styles.css app.js vendor images; do
  if [ -e "$relative" ]; then
    rm -rf "output/$relative"
    if [ -d "$relative" ]; then
      cp -R "$relative" "output/$relative"
    else
      cp "$relative" "output/$relative"
    fi
  fi
done
for pattern in '*.jinja' '*.jinja2' '*.j2' '*.yaml' '*.yml'; do
  while IFS= read -r leaked; do
    [ -n "$leaked" ] || continue
    printf 'public output guard: removed template/config file: %s\n' "$leaked" >&2
    rm -f "$leaked"
  done < <(find output -type f -name "$pattern" -print)
done

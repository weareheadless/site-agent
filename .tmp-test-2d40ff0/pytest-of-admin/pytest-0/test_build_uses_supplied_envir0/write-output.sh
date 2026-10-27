#!/usr/bin/env bash
set -eu
mkdir -p output
printf '%s' "${INTAKE_LAB_OPERATOR_SECRET:-missing}" > output/index.html

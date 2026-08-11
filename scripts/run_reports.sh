#!/usr/bin/env sh
set -eu

seo-pipeline report --site all --provider "${SEO_PIPELINE_PROVIDER:-openseo}"


#!/bin/bash
# Builds the walkthrough template Designed Living fills with one house. Run in the cloud (npm), never needed on the PC.
set -e
cd "$(dirname "$0")"
npx esbuild src/main.js --bundle --minify --format=iife --legal-comments=inline --outfile=dist/bundle.js --log-level=warning
python3 - <<'PY'
b = open('dist/bundle.js').read()
assert '</script' not in b.lower() and '/*__HOUSE_JSON__*/' not in b
t = open('src/template.html').read()
open('dist/walkthrough-template.html', 'w').write(t.replace('/*__BUNDLE__*/', b))
PY
ls -la dist

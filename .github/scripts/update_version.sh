#!/usr/bin/env bash
VERSION=$1
echo "Detected version: $VERSION"
cat << EOF > cos/__version__.py
__version__ = "$VERSION"
EOF
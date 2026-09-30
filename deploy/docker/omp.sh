#!/bin/sh
# The compiled native loader uses ~/.omp even when PI_CONFIG_DIR is set.
# Limit HOME to this process so Codex, Claude and media tools remain unchanged.
export HOME=/omp
exec /opt/omp/omp "$@"

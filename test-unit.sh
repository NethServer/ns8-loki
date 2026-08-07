#!/bin/bash

#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#

# Run the unit tests in a container.
#
#   ./test-unit.sh [PYTEST ARG]...

set -e -a

venvroot=/usr/local/venv

exec podman run -i --rm \
    --volume=.:/srv/source:z \
    --volume=pytest-cache:${venvroot}:z \
    --replace --name=pytest-unit \
    --env=venvroot \
    docker.io/python:3.11-alpine \
    ash -l -s -- "${@}" <<'EOF'
set -e
if [ ! -x ${venvroot}/bin/pytest ] ; then
    python3 -mvenv ${venvroot} --upgrade
    ${venvroot}/bin/pip3 install -q -r /srv/source/tests/unit/requirements.txt
fi
cd /srv/source
exec ${venvroot}/bin/pytest -q "${@}" tests/unit/
EOF

#!/bin/bash

LEADER_NODE=$1
SSH_KEYFILE=${SSH_KEYFILE:-$HOME/.ssh/id_rsa}

ssh_key="$(cat $SSH_KEYFILE)"

podman run -i \
    --volume=site-packages:/home/pwuser/.local/lib/python3.8/site-packages:Z \
    -v .:/home/pwuser/ns8-module:z \
    --name rf-core-runner ghcr.io/marketsquare/robotframework-browser/rfbrowser-stable:v10.1.0 \
    bash -l -s <<EOF
    set -e
    echo "$ssh_key" > /home/pwuser/ns8-key
    set -x
    pip install -r /home/pwuser/ns8-module/tests/pythonreq.txt
    mkdir ~/outputs
    cd /home/pwuser/ns8-module
    robot -v NODE_ADDR:${LEADER_NODE} \
        -v SSH_KEYFILE:/home/pwuser/ns8-key \
	-d ~/outputs /home/pwuser/ns8-module/tests/
EOF

tests_res=$?

podman cp rf-core-runner:/home/pwuser/outputs tests/
podman stop rf-core-runner
podman rm rf-core-runner

exit ${tests_res}

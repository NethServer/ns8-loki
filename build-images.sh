#!/bin/bash

set -e
images=()
repobase="${REPOBASE:-ghcr.io/nethserver}"

reponame="loki"
container=$(buildah from scratch)

buildah add "${container}" imageroot /imageroot
buildah add "${container}" ui /ui
buildah config --entrypoint=/ \
	--label="org.nethserver.images=docker.io/traefik:v3.3.4 docker.io/grafana/loki:3.4.2" \
	--label="org.nethserver.min-core=3.2.0-0" \
	--label="org.nethserver.tcp-ports-demand=1" \
    --label='org.nethserver.flags=core_module' \
	"${container}"
buildah commit "${container}" "${repobase}/${reponame}"
images+=("${repobase}/${reponame}")

#
#
#

if [[ -n "${CI}" ]]; then
    # Set output value for Github Actions
    printf "::set-output name=images::%s\n" "${images[*]}"
else
    printf "Publish the images with:\n\n"
    for image in "${images[@]}"; do printf "  buildah push %s docker://%s:latest\n" "${image}" "${image}" ; done
    printf "\n"
fi

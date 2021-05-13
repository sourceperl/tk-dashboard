#!/bin/sh

IMG="dash-admin-shell"
HERE="$( cd -- "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"

echo "build admin env... (this can take a long time)"
docker build -t ${IMG} ${HERE}/. > /dev/null
echo "...[done]"
echo ""

${HERE}/dash-help
docker run -it --rm \
           --net dash-net \
           -v dash-conf-vol:/data/dash-conf-vol \
           ${IMG} bash


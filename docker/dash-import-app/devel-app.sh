#!/bin/sh

IMG="dash-import-app-img"
HERE="$( cd -- "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"

echo "run app.py from \"${HERE}\" in container based on \"${IMG}\" image"
docker run -it --rm \
           --net dash-net \
           -v dash-conf-vol:/data/dashboard-conf-vol \
           -v ${HERE}:/usr/src/app \
           ${IMG} python3 app.py
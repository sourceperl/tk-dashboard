#!/bin/sh

IMG="dash-init"
HERE="$( cd -- "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"

echo "build init env... (this can take a long time)"
docker build -t ${IMG} ${HERE}/. > /dev/null
echo "...[done]"

echo ""
echo "-------------------------------------------------------------------------------"
echo "do some init stuff from here"
echo "run \"vim /data/dash-conf-vol/dashboard.conf\" to edit configuration file"
echo "run \"./init-static.py\" to add static content (PNG image...) to redis DB"
echo "-------------------------------------------------------------------------------"
docker run -it --rm \
           --net dash-net \
           -v dash-conf-vol:/data/dash-conf-vol \
           ${IMG} bash
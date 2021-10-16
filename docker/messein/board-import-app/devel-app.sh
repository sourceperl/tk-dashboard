#!/bin/sh

IMG="board-import-app-img"
HERE="$( cd -- "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"

echo "/usr/src/app is link to ${HERE}"
echo "run \"python3 app.py\" to test app.py update with ${IMG} docker image"
docker run -it --rm \
           --net board-net \
           -v /etc/opt/tk-dashboard:/data/conf:ro \
           -v ${HERE}:/usr/src/app:rw \
           ${IMG} bash
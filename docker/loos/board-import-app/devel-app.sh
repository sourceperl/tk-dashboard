#!/bin/sh

IMG="board-import-app-img"
HERE="$( cd -- "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"

echo "/usr/src/app/app.py is link to ${HERE}/app.py"
echo "run \"python3 app.py\" to test app.py update with ${IMG} docker image"
docker run -it --rm \
           --net board-net \
           -v /etc/opt/tk-dashboard/board.conf:/data/conf/board.conf:ro \
           -v ${HERE}/app.py:/usr/src/app/app.py:rw \
           ${IMG} bash

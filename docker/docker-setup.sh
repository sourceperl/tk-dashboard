#!/bin/bash

# build base images
docker build -t board-debian-base-img common/board-debian-base/.
docker build -t board-py3-base-img common/board-py3-base/.

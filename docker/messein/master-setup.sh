#!/bin/sh

# build base image
docker build -t board-py3-base-img board-py3-base/.

# start the stack
docker-compose -f master-compose.yml up  -d

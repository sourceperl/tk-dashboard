#!/bin/sh

# start the stack
docker-compose --file messein/master-compose.yml --env-file messein/.env up -d

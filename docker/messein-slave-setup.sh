#!/bin/sh

# start the stack
docker-compose --file messein/slave-compose.yml --env-file messein/.env up -d

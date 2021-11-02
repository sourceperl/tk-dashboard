#!/bin/sh

# start the stack
docker-compose --file loos/slave-compose.yml --env-file loos/.env up -d

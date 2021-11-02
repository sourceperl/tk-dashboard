#!/bin/sh

# start the stack
docker-compose --file loos/master-compose.yml --env-file loos/.env up -d

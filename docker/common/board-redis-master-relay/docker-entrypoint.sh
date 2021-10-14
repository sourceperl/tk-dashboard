#!/bin/sh

# check mandatory args before command run
if [ -z "$SSH_TARGET" ]; then
  echo 'container failed to start: you must define env var SSH_TARGET (for example with "pi@192.168.0.60")'
  exit 1
fi

exec "$@"

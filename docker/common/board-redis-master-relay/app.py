#!/usr/bin/env python3

# WARN: You must share ssh key before use it (see README)

from configparser import ConfigParser
import logging
import os
import subprocess


# logging setup
logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)

# read config
cnf = ConfigParser()
cnf.read(os.path.expanduser('/data/conf/dashboard.conf'))
master_host = cnf.get('dashboard', 'master_host')

# format autossh args (some can be overide by environment vars)
ssh_args = '-o ServerAliveInterval=10 -o ServerAliveCountMax=3'
port_map = '0.0.0.0:6379:127.0.0.1:6379'
ssh_target = f'pi@{master_host}'

try:
    cmd = f'autossh -M 0 -NT -L {port_map} {ssh_args} {ssh_target}'
    logging.info(f'call "{cmd}"')
    subprocess.call(cmd.split())
except Exception as e:
    logging.error(f'except {type(e)}: {e}')

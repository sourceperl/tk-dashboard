#!/usr/bin/env python3

# WARN: You must share ssh key before use it (see README)

from configparser import ConfigParser
import logging
import time
import subprocess


# some const
DASHBOARD_DATA_HMI_PATH = '/srv/dashboard/hmi/'

# read config
cnf = ConfigParser()
cnf.read('/etc/opt/tk-dashboard/dashboard.conf')
# hostname of master dashboard
master_host = cnf.get('dashboard', 'master_host')


def cold_file_sync_job():
    # mirror master dashboard hmi files to slave one
    try:
        cmd = 'rsync -aALxX --delete %s:%s. %s.'
        cmd %= master_host, DASHBOARD_DATA_HMI_PATH, DASHBOARD_DATA_HMI_PATH
        subprocess.call(cmd.split())
    except Exception as e:
        logging.error(f'except {type(e)} in cold_file_sync_job(): {e}')


# main
if __name__ == '__main__':
    # logging setup
    logging.basicConfig(format='%(asctime)s %(message)s')

    # main loop
    while True:
        cold_file_sync_job()
        time.sleep(5 * 60)

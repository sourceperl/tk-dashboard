#!/usr/bin/env python3

# WARN: You must share ssh key before use it (see README)

from configparser import ConfigParser
import logging
import os
import time
import schedule
import subprocess


# some const
DASHBOARD_DATA_HMI_PATH = '/srv/dashboard/hmi/'

# read config
cnf = ConfigParser()
cnf.read(os.path.expanduser('~/.dashboard_config'))
# hostname of master dashboard
dash_master_host = cnf.get('dashboard', 'master_host')


def cold_file_sync_job():
    # mirror master dashboard root path (like /home/pi/dashboard/) -> to slave one
    try:
        cmd = 'rsync -aALxX --delete %s:%s. %s.'
        cmd %= dash_master_host, DASHBOARD_DATA_HMI_PATH, DASHBOARD_DATA_HMI_PATH
        subprocess.call(cmd.split())
    except Exception as e:
        logging.error(f'except {type(e)} in cold_file_sync_job(): {e}')


# main
if __name__ == '__main__':
    # logging setup
    logging.basicConfig(format='%(asctime)s %(message)s')

    # init scheduler
    schedule.every(5).minutes.do(cold_file_sync_job)
    # first call
    cold_file_sync_job()

    # main loop
    while True:
        schedule.run_pending()
        time.sleep(1)

#!/usr/bin/env python3

# WARN: You must share ssh key before use it (see README)

from configparser import ConfigParser
import logging
import os
import time
import traceback
import schedule
import subprocess

# read config
cnf = ConfigParser()
cnf.read(os.path.expanduser('~/.dashboard_config'))
# hostname of master dashboard
dash_master_host = cnf.get("dashboard", "master_host")
#dashboard_ramdisk = cnf.get("paths", "dashboard_ramdisk")
dashboard_root_path = cnf.get("paths", "dashboard_root_path")


def hot_file_sync_job():
    # mirror master dashboard ramdisk (like /media/ramdisk/) -> slave ramdisk
    try:
        cmd = "rsync -aAxX --delete --omit-dir-times %s:%s. %s."
        cmd %= dash_master_host, dashboard_ramdisk, dashboard_ramdisk
        subprocess.call(cmd.split())
    except Exception:
        logging.error(traceback.format_exc())
        return None


def cold_file_sync_job():
    # mirror master dashboard root path (like /home/pi/dashboard/) -> to slave one
    try:
        cmd = "rsync -aAxX --delete %s:%s. %s."
        cmd %= dash_master_host, dashboard_root_path, dashboard_root_path
        subprocess.call(cmd.split())
    except Exception:
        logging.error(traceback.format_exc())
        return None


# main
if __name__ == '__main__':
    # logging setup
    logging.basicConfig(format='%(asctime)s %(message)s')

    # init scheduler
    #schedule.every(1).minute.do(hot_file_sync_job)
    schedule.every(5).minutes.do(cold_file_sync_job)
    # first call
    #hot_file_sync_job()
    cold_file_sync_job()

    # main loop
    while True:
        schedule.run_pending()
        time.sleep(1)

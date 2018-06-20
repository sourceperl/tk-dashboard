#!/usr/bin/env python3

# WARN: You must share ssh key before use it (see README)

import logging
import time
import traceback
import schedule
import subprocess

# some const
IP_MASTER_DASHBOARD = "192.168.0.60"


def hot_file_sync_job():
    # mirror master dashboard /media/ramdisk/ -> slave /media/ramdisk/
    try:
        cmd = "rsync -aAxX --delete --omit-dir-times %s:/media/ramdisk/. /media/ramdisk/."
        cmd %= IP_MASTER_DASHBOARD
        subprocess.call(cmd.split())
    except Exception:
        logging.error(traceback.format_exc())
        return None


def cold_file_sync_job():
    # mirror master dashboard /home/pi/dashboard/ -> slave /home/pi/dashboard/
    try:
        cmd = "rsync -aAxX --delete %s:/home/pi/dashboard/. /home/pi/dashboard/."
        cmd %= IP_MASTER_DASHBOARD
        subprocess.call(cmd.split())
    except Exception:
        logging.error(traceback.format_exc())
        return None


# main
if __name__ == '__main__':
    # logging setup
    logging.basicConfig(format='%(asctime)s %(message)s')

    # init scheduler
    schedule.every(1).minute.do(hot_file_sync_job)
    schedule.every(5).minutes.do(cold_file_sync_job)
    # first call
    hot_file_sync_job()
    cold_file_sync_job()

    # main loop
    while True:
        schedule.run_pending()
        time.sleep(1)

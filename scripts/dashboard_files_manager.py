#!/usr/bin/env python3

from configparser import ConfigParser
import logging
import os
from os.path import isfile, join
import time
import traceback
import schedule
import subprocess

# read config
cnf = ConfigParser()
cnf.read(os.path.expanduser('~/.dashboard_config'))
dashboard_root_path = cnf.get("paths", "dashboard_root_path")
carousel_img_path = dashboard_root_path + cnf.get("paths", "carousel_img_dir")
carousel_max_png = int(cnf.get("carousel", "max_png", fallback=4))


# some functions
def ls_files(path, ext=""):
    return [join(path, file) for file in os.listdir(path) if isfile(join(path, file)) and file.endswith(ext)]


def manage_display_dir_job():
    try:
        # for all files in display dir
        for f in ls_files(carousel_img_path):
            # PDF files
            if f.endswith(".pdf"):
                # convert pdf -> png with resize
                subprocess.call("mogrify -density 500 -resize 655x453 -format png".split() + [f])
                # delete file
                os.remove(f)

        # remove older one
        for f in sorted(ls_files(carousel_img_path, ext=".png"), key=os.path.getctime)[:-carousel_max_png]:
            # delete file
            os.remove(f)
    except Exception:
        logging.error(traceback.format_exc())
        return None

# main
if __name__ == '__main__':
    # logging setup
    logging.basicConfig(format='%(asctime)s %(message)s')

    # init scheduler
    schedule.every(60).minutes.do(manage_display_dir_job)
    # first call
    manage_display_dir_job()

    # main loop
    while True:
        schedule.run_pending()
        time.sleep(1)

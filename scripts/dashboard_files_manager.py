#!/usr/bin/env python3

from configparser import ConfigParser
import logging
import os
from os.path import splitext, isfile, join
import time
import traceback
import shutil
import subprocess
import schedule
import redis

# read config
cnf = ConfigParser()
cnf.read(os.path.expanduser('~/.dashboard_config'))
dashboard_root_path = cnf.get("paths", "dashboard_root_path")
carousel_img_path = dashboard_root_path + cnf.get("paths", "carousel_img_dir")
carousel_upload_dir = dashboard_root_path + cnf.get("paths", "carousel_upload_dir")
carousel_max_png = int(cnf.get("carousel", "max_png", fallback=4))


# some functions
def ls_files(path, ext=""):
    return [join(path, file) for file in os.listdir(path) if isfile(join(path, file)) and file.endswith(ext)]


def manage_carousel_job():
    try:
        # for all files in display dir
        for f in ls_files(carousel_upload_dir):
            # PDF files
            if f.endswith(".pdf"):
                # convert pdf -> png with resize
                subprocess.call("mogrify -density 500 -resize 655x453 -format png".split() + [f])
                # move png file from upload dir to img dir
                shutil.move(splitext(f)[0] + ".png", carousel_img_path)
                # delete pdf file
                os.remove(f)

        # remove older png file
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

    # subscribe to redis publish channel
    r = redis.StrictRedis()
    ps = r.pubsub()
    ps.subscribe(["dashboard:trigger"])

    # init scheduler
    schedule.every(60).minutes.do(manage_carousel_job)
    # first call
    manage_carousel_job()

    # main loop
    while True:
        # schedule jobs
        schedule.run_pending()
        # check notify on redis
        try:
            msg = ps.get_message()
            if msg and msg["type"] == "message":
                # immediate carousel update on redis notify
                if msg["data"].decode() == "carousel_update":
                    manage_carousel_job()
        except Exception:
            logging.error(traceback.format_exc())
        # wait next loop
        time.sleep(1)

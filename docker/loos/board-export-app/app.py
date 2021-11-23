#!/usr/bin/env python3

from board_lib import CustomRedis, catch_log_except, dweet_encode
from configparser import ConfigParser
import logging
import time
import requests
import schedule

# read config
cnf = ConfigParser()
cnf.read('/data/conf/board.conf')
# redis
redis_user = cnf.get('redis', 'user')
redis_pass = cnf.get('redis', 'pass')
# dweet
dweet_id = cnf.get('dweet', 'id')
dweet_key = cnf.get('dweet', 'key')


# some class
class DB:
    main = CustomRedis(host='board-redis-srv', username=redis_user, password=redis_pass,
                       socket_timeout=4, socket_keepalive=True)


@catch_log_except()
def dweet_job():
    DW_POST_URL = 'https://dweet.io/dweet/for/'

    # read internal data
    json_flyspray_nord = DB.main.get('json:bridge:fly-nord')
    json_flyspray_est = DB.main.get('json:bridge:fly-est')
    # populate dweet_post_d dict with encoded json
    dweet_post_d = {}
    if json_flyspray_nord:
        dweet_post_d['raw_flyspray_nord'] = dweet_encode(json_flyspray_nord, dweet_key).decode('ascii')
    if json_flyspray_est:
        dweet_post_d['raw_flyspray_est'] = dweet_encode(json_flyspray_est, dweet_key).decode('ascii')
    # if dweet_post_d not empty publish to dweet
    if dweet_post_d:
        r = requests.post(DW_POST_URL + dweet_id, json=dweet_post_d, timeout=15.0)
        # check error
        if r.status_code == 200:
            logging.debug("dweet update ok")


@catch_log_except()
def redis_export_job():
    # fill Messein share keyspace
    for k in ['img:grt-twitter-cloud:png', 'json:tweets:@grtgaz']:
        DB.main.execute_command('COPY', k, f'share:messein:{k}', 'REPLACE')


# main
if __name__ == '__main__':
    # logging setup
    logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)
    logging.info('board-export-app started')

    # init scheduler
    schedule.every(5).minutes.do(dweet_job)
    schedule.every(2).minutes.do(redis_export_job)
    # first call
    dweet_job()
    redis_export_job()

    # main loop
    while True:
        schedule.run_pending()
        time.sleep(1)

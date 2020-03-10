#!/usr/bin/env python3

from configparser import ConfigParser
import base64
import json
import logging
import math
import os
import time
import traceback
import redis
import requests
import schedule

# read config
cnf = ConfigParser()
cnf.read(os.path.expanduser('~/.dashboard_config'))
# hostname of master dashboard
dash_master_host = cnf.get("dashboard", "master_host")
# hostname of bridge server
bridge_host = cnf.get("bridge", "bridge_host")
# dweet
dweet_id = cnf.get('dweet', 'id')
dweet_key = cnf.get('dweet', 'key')


class CustomRedis(redis.StrictRedis):
    def get_str(self, name):
        try:
            return self.get(name).decode('utf-8')
        except (redis.RedisError, AttributeError):
            return None

    def get_obj(self, name):
        try:
            return json.loads(self.get(name).decode('utf-8'))
        except (redis.RedisError, AttributeError, json.decoder.JSONDecodeError):
            return None

    def set_str(self, name, value):
        try:
            return self.set(name, value)
        except redis.RedisError:
            return None

    def set_obj(self, name, obj):
        try:
            return self.set(name, json.dumps(obj))
        except (redis.RedisError, AttributeError, json.decoder.JSONDecodeError):
            return None

    def set_ttl(self, name, ttl=3600):
        try:
            return self.expire(name, ttl)
        except redis.RedisError:
            return None


class DB:
    # create connector
    master = CustomRedis(host=dash_master_host, socket_timeout=4, socket_keepalive=True)
    bridge = CustomRedis(host=bridge_host, socket_timeout=4, socket_keepalive=True)


# some function
def byte_xor(bytes_1, bytes_2):
    return bytes([_a ^ _b for _a, _b in zip(bytes_1, bytes_2)])


def dweet_encode(bytes_msg):
    # build xor mask (size will be >= msg size)
    xor_mask = dweet_key.encode('utf8')
    xor_mask *= math.ceil(len(bytes_msg) / len(xor_mask))
    # do xor
    xor_result = byte_xor(xor_mask, bytes_msg)
    # encode result in base64 (for no utf-8 byte support)
    return base64.b64encode(xor_result)


def dweet_decode(b64_bytes_msg):
    # decode base64 msg
    bytes_msg = base64.b64decode(b64_bytes_msg)
    # build xor mask (size will be >= msg size)
    xor_mask = dweet_key.encode('utf8')
    xor_mask *= math.ceil(len(bytes_msg) / len(xor_mask))
    # do xor and return clear bytes msg
    return byte_xor(xor_mask, bytes_msg)


def dweet_job():
    DW_POST_URL = 'https://dweet.io/dweet/for/'

    try:
        # read internal data
        json_flyspray_nord = DB.bridge.get('rx:bur:flyspray_rss_nord')
        json_flyspray_est = DB.bridge.get('rx:bur:flyspray_rss_est')
        # encode
        raw_flyspray_nord = dweet_encode(json_flyspray_nord)
        raw_flyspray_est = dweet_encode(json_flyspray_est)
        # do export request
        dweet_post_d = dict(raw_flyspray_nord=raw_flyspray_nord,
                            raw_flyspray_est=raw_flyspray_est)
        r = requests.post(DW_POST_URL + dweet_id, json=dweet_post_d, timeout=15.0)
        # check error
        if r.status_code == 200:
            logging.debug("dweet update ok")
    except Exception:
        logging.error(traceback.format_exc())
        return None


# main
if __name__ == '__main__':
    # logging setup
    logging.basicConfig(format='%(asctime)s %(message)s')
    # logging.basicConfig(format='%(asctime)s %(message)s', level=logging.DEBUG)

    # init scheduler
    schedule.every(5).minutes.do(dweet_job)
    # first call
    dweet_job()

    # main loop
    while True:
        schedule.run_pending()
        time.sleep(1)

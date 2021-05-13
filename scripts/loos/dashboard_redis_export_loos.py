#!/usr/bin/env python3

from configparser import ConfigParser
import base64
import json
import logging
import math
import os
import secrets
import time
import traceback
import zlib
import redis
import requests
import schedule

# read config
cnf = ConfigParser()
cnf.read(os.path.expanduser('~/.dashboard_config'))
# dweet
dweet_id = cnf.get('dweet', 'id')
dweet_key = cnf.get('dweet', 'key')


class CustomRedis(redis.StrictRedis):
    def set_ttl(self, name, ttl=3600):
        try:
            return self.expire(name, ttl)
        except redis.RedisError:
            logging.error(traceback.format_exc())

    def set_bytes(self, name, value):
        try:
            return self.set(name, value)
        except redis.RedisError:
            logging.error(traceback.format_exc())

    def get_bytes(self, name):
        try:
            return self.get(name)
        except redis.RedisError:
            logging.error(traceback.format_exc())

    def set_str(self, name, value):
        try:
            return self.set(name, value)
        except redis.RedisError:
            logging.error(traceback.format_exc())

    def get_str(self, name):
        try:
            return self.get(name).decode('utf-8')
        except (redis.RedisError, AttributeError):
            logging.error(traceback.format_exc())

    def set_to_json(self, name, obj):
        try:
            return self.set(name, json.dumps(obj))
        except (redis.RedisError, AttributeError, json.decoder.JSONDecodeError):
            logging.error(traceback.format_exc())

    def get_from_json(self, name):
        try:
            return json.loads(self.get(name).decode('utf-8'))
        except (redis.RedisError, AttributeError, json.decoder.JSONDecodeError):
            logging.error(traceback.format_exc())


class DB:
    # create connector
    master = CustomRedis(host='localhost', socket_timeout=4, socket_keepalive=True)


# some function
def byte_xor(bytes_1, bytes_2):
    return bytes([_a ^ _b for _a, _b in zip(bytes_1, bytes_2)])


def dweet_encode(bytes_data):
    # compress data
    c_data = zlib.compress(bytes_data)
    # generate a random token
    token = secrets.token_bytes(64)
    # xor random token and private key
    key = dweet_key.encode('utf8')
    key_mask = key * math.ceil(len(token) / len(key))
    xor_token = byte_xor(token, key_mask)
    # xor data and token
    token_mask = token * math.ceil(len(c_data) / len(token))
    xor_data = byte_xor(c_data, token_mask)
    # concatenate xor random token and xor data
    msg_block = xor_token + xor_data
    # encode result in base64 (for no utf-8 byte support)
    return base64.b64encode(msg_block)


def dweet_decode(b64_msg_block):
    # decode base64 msg
    msg_block = base64.b64decode(b64_msg_block)
    # split message: [xor_token part : xor_data part]
    xor_token = msg_block[:64]
    xor_data = msg_block[64:]
    # token = xor_token xor private key
    key = dweet_key.encode('utf8')
    key_mask = key * math.ceil(len(xor_token) / len(key))
    token = byte_xor(xor_token, key_mask)
    # compressed data = xor_data xor token
    token_mask = token * math.ceil(len(xor_data) / len(token))
    c_data = byte_xor(xor_data, token_mask)
    # return decompress data
    return zlib.decompress(c_data)


def dweet_job():
    DW_POST_URL = 'https://dweet.io/dweet/for/'

    try:
        # read internal data
        json_flyspray_nord = DB.master.get_bytes('bridge:flyspray_rss_nord')
        json_flyspray_est = DB.master.get_bytes('bridge:flyspray_rss_est')
        # populate dweet_post_d dict with encoded json
        dweet_post_d = {}
        if json_flyspray_nord:
            dweet_post_d['raw_flyspray_nord'] = dweet_encode(json_flyspray_nord)
        if json_flyspray_est:
            dweet_post_d['raw_flyspray_est'] = dweet_encode(json_flyspray_est)
        # if dweet_post_d not empty publish to dweet
        if dweet_post_d:
            r = requests.post(DW_POST_URL + dweet_id, json=dweet_post_d, timeout=15.0)
            # check error
            if r.status_code == 200:
                logging.debug("dweet update ok")
    except Exception:
        logging.error(traceback.format_exc())


# main
if __name__ == '__main__':
    # logging setup
    logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)
    logging.info('dashboard_redis_export started')

    # init scheduler
    schedule.every(5).minutes.do(dweet_job)
    # first call
    dweet_job()

    # main loop
    while True:
        schedule.run_pending()
        time.sleep(1)

#!/usr/bin/env python3

from configparser import ConfigParser
import base64
import json
import logging
import functools
import math
import secrets
import time
import zlib
import redis
import requests
import schedule

# read config
cnf = ConfigParser()
cnf.read('/data/board-conf-vol/dashboard.conf')
# dweet
dweet_id = cnf.get('dweet', 'id')
dweet_key = cnf.get('dweet', 'key')


# some function
def catch_log_except(catch=Exception, log_lvl=logging.ERROR):
    # decorator to catch exception and produce one line log message
    def _catch_log_except(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except catch as e:
                func_args = f'{str(args)[1:-1]}'.strip(',')
                func_args += ', ' if args and kwargs else ''
                func_args += f'{str(kwargs)[1:-1]}'
                func_call = f'{func.__name__}({func_args})'
                logging.log(log_lvl, f'except {type(e)} in {func_call}: {e}')

        return wrapper

    return _catch_log_except


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
    # encode binary data with base64
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


# some class
class CustomRedis(redis.StrictRedis):
    @catch_log_except(catch=redis.RedisError)
    def set_ttl(self, name, ttl=3600):
        return self.expire(name, ttl)

    @catch_log_except(catch=redis.RedisError)
    def set_bytes(self, name, value):
        return self.set(name, value)

    @catch_log_except(catch=redis.RedisError)
    def get_bytes(self, name):
        return self.get(name)

    @catch_log_except(catch=redis.RedisError)
    def set_str(self, name, value):
        return self.set(name, value)

    @catch_log_except(catch=(redis.RedisError, AttributeError))
    def get_str(self, name):
        return self.get(name).decode('utf-8')

    @catch_log_except(catch=(redis.RedisError, AttributeError, json.decoder.JSONDecodeError))
    def set_to_json(self, name, obj):
        return self.set(name, json.dumps(obj))

    @catch_log_except(catch=(redis.RedisError, AttributeError, json.decoder.JSONDecodeError))
    def get_from_json(self, name):
        return json.loads(self.get(name).decode('utf-8'))


class DB:
    master = CustomRedis(host='board-redis-srv', socket_timeout=4, socket_keepalive=True)


@catch_log_except()
def dweet_job():
    DW_POST_URL = 'https://dweet.io/dweet/for/'

    # read internal data
    json_flyspray_nord = DB.master.get_bytes('bridge:flyspray_rss_nord')
    json_flyspray_est = DB.master.get_bytes('bridge:flyspray_rss_est')
    # populate dweet_post_d dict with encoded json
    dweet_post_d = {}
    if json_flyspray_nord:
        dweet_post_d['raw_flyspray_nord'] = dweet_encode(json_flyspray_nord).decode('ascii')
    if json_flyspray_est:
        dweet_post_d['raw_flyspray_est'] = dweet_encode(json_flyspray_est).decode('ascii')
    # if dweet_post_d not empty publish to dweet
    if dweet_post_d:
        r = requests.post(DW_POST_URL + dweet_id, json=dweet_post_d, timeout=15.0)
        # check error
        if r.status_code == 200:
            logging.debug("dweet update ok")


# main
if __name__ == '__main__':
    # logging setup
    logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)
    logging.info('board-export-app started')

    # init scheduler
    schedule.every(5).minutes.do(dweet_job)
    # first call
    dweet_job()

    # main loop
    while True:
        schedule.run_pending()
        time.sleep(1)

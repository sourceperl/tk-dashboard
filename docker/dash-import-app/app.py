#!/usr/bin/env python3

from collections import Counter
from configparser import ConfigParser
import urllib.parse
import logging
import io
import re
import time
import traceback
import redis
import requests
from requests_oauthlib import OAuth1
import schedule
import PIL.Image
from wordcloud import WordCloud

# read config
cnf = ConfigParser()
cnf.read('/data/dashboard-conf-vol/dashboard.conf')
# gmap img traffic
gmap_img_url = cnf.get("gmap_img", "img_url")
# twitter
tw_api_key = cnf.get("twitter", "api_key")
tw_api_secret = cnf.get("twitter", "api_secret")
tw_access_token = cnf.get("twitter", "access_token")
tw_access_token_secret = cnf.get("twitter", "access_token_secret")


# some class
class CustomRedis(redis.StrictRedis):
    def set_bytes(self, name, value):
        try:
            return self.set(name, value)
        except redis.RedisError as e:
            logging.error(e)

    def set_ttl(self, name, ttl=3600):
        try:
            return self.expire(name, ttl)
        except redis.RedisError as e:
            logging.error(e)


class DB:
    # create connector
    master = CustomRedis(host='dash-redis-srv', socket_timeout=4, socket_keepalive=True)


# some function
def twitter2cloud_job():
    def is_camelcase(s):
        return s != s.lower() and "_" not in s

    try:
        # params
        tw_query = 'grtgaz exclude:retweets exclude:replies'
        tw_count = 100
        tw_oauth = OAuth1(tw_api_key, tw_api_secret, tw_access_token, tw_access_token_secret)
        # build url
        url = 'https://api.twitter.com/1.1/search/tweets.json?'
        url += 'q=%s&count=%i&result_type=recent&tweet_mode=extended'
        url %= (urllib.parse.quote(tw_query), tw_count)
        # do request
        r = requests.get(url, auth=tw_oauth, timeout=5.0)
        # check error
        if r.status_code == 200:
            d_tweets = r.json()
            d_hash_camel = {}
            c_hash = Counter()
            for tw in d_tweets['statuses']:
                tw_msg = tw['full_text']
                # search hashtag and count it
                for hashtag in re.findall(r'#(\w+)', tw_msg):
                    h_key = hashtag.lower()
                    if is_camelcase(hashtag):
                        d_hash_camel[h_key] = hashtag
                    elif h_key not in d_hash_camel:
                        d_hash_camel[h_key] = h_key
                    c_hash.update([h_key])

            # build WordCloud
            if c_hash:
                # build frequencies dict for generate step
                d_freq = {}
                for h_key, score in c_hash.most_common(25):
                    d_freq[d_hash_camel[h_key]] = score
                # generate a word cloud image
                word_cloud = WordCloud(margin=5, width=327, height=226)
                word_cloud.generate_from_frequencies(frequencies=d_freq)
                img_io = io.BytesIO()
                pil_img = word_cloud.to_image()
                pil_img.save(img_io, format='PNG')
                # store RAW PNG to redis key
                DB.master.set_bytes('img:grt-tweet-wordcloud:png', img_io.getvalue())
                DB.master.set_ttl('img:grt-tweet-wordcloud:png', 7200)
    except Exception:
        logging.error(traceback.format_exc())


def gmap_traffic_img_job():
    # http request
    try:
        r = requests.get(gmap_img_url, stream=True, timeout=5.0)
        if r.status_code == 200:
            # convert RAW img format (bytes) to Pillow image
            pil_img = PIL.Image.open(io.BytesIO(r.raw.read()))
            # resize to 632x328 and force png format
            pil_img.thumbnail([632, 328])
            img_io = io.BytesIO()
            pil_img.save(img_io, format='PNG')
            # store RAW PNG to redis key
            DB.master.set_bytes('img:traffic-map:png', img_io.getvalue())
            DB.master.set_ttl('img:traffic-map:png', 7200)
    except Exception:
        logging.error(traceback.format_exc())


# main
if __name__ == '__main__':
    # logging setup
    logging.basicConfig(format='%(asctime)s %(message)s')

    # init scheduler
    schedule.every(2).minutes.do(gmap_traffic_img_job)
    schedule.every(30).minutes.do(twitter2cloud_job)
    # first call
    gmap_traffic_img_job()
    twitter2cloud_job()

    # main loop
    while True:
        schedule.run_pending()
        time.sleep(1)

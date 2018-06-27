#!/usr/bin/env python3

from collections import Counter
from configparser import ConfigParser
import logging
import os
import re
import time
import traceback
import requests
from requests_oauthlib import OAuth1
import schedule
import shutil
import urllib.parse
from wordcloud import WordCloud

# some const
# GRTgaz Colors
BLEU = "#007bc2"
VERT = "#00a984"
ARDOISE = "#3c4f69"
MARINE = "#154194"
FUSHIA = "#e5007d"
ORANGE = "#f39200"
JAUNE = "#ffe200"

# read config
cnf = ConfigParser()
cnf.read(os.path.expanduser('~/.dashboard_config'))
# gmap img traffic
gmap_img_url = cnf.get("gmap_img", "img_url")
gmap_img_target = cnf.get("gmap_img", "img_target")
# twitter
tw_api_key = cnf.get("twitter", "api_key")
tw_api_secret = cnf.get("twitter", "api_secret")
tw_access_token = cnf.get("twitter", "access_token")
tw_access_token_secret = cnf.get("twitter", "access_token_secret")
tw_cloud_img = cnf.get("twitter", "cloud_img")


# some function
def twitter2cloud_job():
    def is_camelcase(s):
        return s != s.lower() and "_" not in s

    try:
        # params
        tw_query = "grtgaz exclude:retweets exclude:replies"
        tw_count = 100
        tw_oauth = OAuth1(tw_api_key, tw_api_secret, tw_access_token, tw_access_token_secret)
        # build url
        url = "https://api.twitter.com/1.1/search/tweets.json?"
        url += "q=%s&count=%i&result_type=recent&tweet_mode=extended"
        url %= (urllib.parse.quote(tw_query), tw_count)
        # do request
        r = requests.get(url, auth=tw_oauth)
        # check error
        if r.status_code == 200:
            d_tweets = r.json()
            d_hash_camel = {}
            c_hash = Counter()
            for tw in d_tweets["statuses"]:
                tw_msg = tw["full_text"]
                # search hashtag and count it
                for hashtag in re.findall(r"#(\w+)", tw_msg):
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
                for h_key, score in c_hash.most_common(30):
                    d_freq[d_hash_camel[h_key]] = score
                # generate a word cloud image
                word_cloud = WordCloud(margin=5, width=327, height=226, background_color=VERT)
                word_cloud.generate_from_frequencies(frequencies=d_freq)
                tw_cloud_img_build = "%s.build.png" % tw_cloud_img
                word_cloud.to_file(tw_cloud_img_build)
                # replace target file with *.dwl version
                shutil.move(tw_cloud_img_build, tw_cloud_img)
    except Exception:
        logging.error(traceback.format_exc())
        return None


def gmap_traffic_img_job():
    # http request
    try:
        r = requests.get(gmap_img_url, stream=True)
        if r.status_code == 200:
            # download as *.dwl file
            download_file = "%s.dwl" % gmap_img_target
            with open(download_file, 'wb') as f:
                r.raw.decode_content = True
                shutil.copyfileobj(r.raw, f)
            # replace target file with *.dwl version
            shutil.move(download_file, gmap_img_target)
    except requests.exceptions.RequestException:
        logging.error(traceback.format_exc())
        return None


# main
if __name__ == '__main__':
    # logging setup
    logging.basicConfig(format='%(asctime)s %(message)s')

    # init scheduler
    schedule.every(2).minutes.do(gmap_traffic_img_job)
    schedule.every(60).minutes.do(twitter2cloud_job)
    # first call
    gmap_traffic_img_job()
    twitter2cloud_job()
    print("done")

    # main loop
    while True:
        schedule.run_pending()
        time.sleep(1)

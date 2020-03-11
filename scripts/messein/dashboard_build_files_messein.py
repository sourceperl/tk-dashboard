#!/usr/bin/env python3

from collections import Counter
from configparser import ConfigParser
import logging
import io
import os
import re
import time
import traceback
import requests
from requests_oauthlib import OAuth1
import schedule
import shutil
import urllib.parse
from PIL import Image
from wordcloud import WordCloud


# read config
cnf = ConfigParser()
cnf.read(os.path.expanduser('~/.dashboard_config'))
# paths
dashboard_ramdisk = cnf.get("paths", "dashboard_ramdisk")
# gmap img traffic
gmap_img_url = cnf.get("gmap_img", "img_url")
gmap_img_target = dashboard_ramdisk + cnf.get("gmap_img", "img_target")
# twitter
tw_api_key = cnf.get("twitter", "api_key")
tw_api_secret = cnf.get("twitter", "api_secret")
tw_access_token = cnf.get("twitter", "access_token")
tw_access_token_secret = cnf.get("twitter", "access_token_secret")
tw_cloud_img = dashboard_ramdisk + cnf.get("twitter", "cloud_img")


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
        r = requests.get(url, auth=tw_oauth, timeout=5.0)
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
                for h_key, score in c_hash.most_common(25):
                    d_freq[d_hash_camel[h_key]] = score
                # generate a word cloud image
                word_cloud = WordCloud(margin=5, width=327, height=226)
                word_cloud.generate_from_frequencies(frequencies=d_freq)
                tw_cloud_img_build = "%s.build.png" % tw_cloud_img
                word_cloud.to_file(tw_cloud_img_build)
                # replace target file with *.dwl version
                shutil.move(tw_cloud_img_build, tw_cloud_img)
    except Exception:
        logging.error(traceback.format_exc())


def gmap_traffic_img_job():
    # http request
    try:
        r = requests.get(gmap_img_url, stream=True, timeout=5.0)
        if r.status_code == 200:
            # download as *.dwl file
            download_file = "%s.dwl" % gmap_img_target
            with open(download_file, 'wb') as f:
                r.raw.decode_content = True
                shutil.copyfileobj(r.raw, f)
            # replace target file with *.dwl version
            shutil.move(download_file, gmap_img_target)
    except Exception:
        logging.error(traceback.format_exc())


# retrieve DIR-est web images
def dir_est_img_job():
    # http request
    try:
        for id_cam in ["laxou", "houpette", "mulhouse2"]:
            r = requests.get("http://oeil.dir-est.fr/consultation-pub/?clusterCameraCode=%s" % id_cam)
            if r.status_code == 200:
                # resize image and it save to ramdisk
                img = Image.open(io.BytesIO(r.content))
                img.thumbnail([224, 235])
                img.save(dashboard_ramdisk + "dir_%s.png" % id_cam, "PNG")
    except Exception:
        logging.error(traceback.format_exc())


# main
if __name__ == '__main__':
    # logging setup
    logging.basicConfig(format='%(asctime)s %(message)s')

    # init scheduler
    schedule.every(2).minutes.do(gmap_traffic_img_job)
    schedule.every(5).minutes.do(dir_est_img_job)
    schedule.every(30).minutes.do(twitter2cloud_job)
    # first call
    gmap_traffic_img_job()
    dir_est_img_job()
    twitter2cloud_job()

    # main loop
    while True:
        schedule.run_pending()
        time.sleep(1)

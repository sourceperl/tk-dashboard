#!/usr/bin/env python3

from collections import OrderedDict
from configparser import ConfigParser
from datetime import datetime
import base64
import feedparser
import html
import json
import logging
import math
import os
import time
import traceback
import zlib
from bs4 import BeautifulSoup
import redis
import requests
from requests_oauthlib import OAuth1
import schedule
import pytz
from xml.dom import minidom


# some const
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:2.0.1) Gecko/20100101 Firefox/4.0.1"
DW_GET_URL = 'https://dweet.io/get/latest/dweet/for/'

# read config
cnf = ConfigParser()
cnf.read(os.path.expanduser('~/.dashboard_config'))
# hostname of master dashboard
dash_master_host = cnf.get("dashboard", "master_host")
# gsheet
gsheet_url = cnf.get('gsheet', 'url')
# openweathermap
ow_app_id = cnf.get('openweathermap', 'app_id')
# twitter
tw_api_key = cnf.get("twitter", "api_key")
tw_api_secret = cnf.get("twitter", "api_secret")
tw_access_token = cnf.get("twitter", "access_token")
tw_access_token_secret = cnf.get("twitter", "access_token_secret")
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


# some function
def byte_xor(bytes_1, bytes_2):
    return bytes([_a ^ _b for _a, _b in zip(bytes_1, bytes_2)])


def dweet_encode(bytes_msg):
    # compress msg
    c_bytes_msg = zlib.compress(bytes_msg)
    # build xor mask (size will be >= msg size)
    xor_mask = dweet_key.encode('utf8')
    xor_mask *= math.ceil(len(bytes_msg) / len(xor_mask))
    # do xor
    xor_result = byte_xor(xor_mask, c_bytes_msg)
    # encode result in base64 (for no utf-8 byte support)
    return base64.b64encode(xor_result)


def dweet_decode(b64_bytes_msg):
    # decode base64 msg
    xor_bytes_msg = base64.b64decode(b64_bytes_msg)
    # build xor mask (size will be >= msg size)
    xor_mask = dweet_key.encode('utf8')
    xor_mask *= math.ceil(len(xor_bytes_msg) / len(xor_mask))
    # do xor
    c_bytes_msg = byte_xor(xor_mask, xor_bytes_msg)
    # do xor and return clear bytes msg
    return zlib.decompress(c_bytes_msg)


def dweet_job():
    # https request
    try:
        r = requests.get(DW_GET_URL + dweet_id, timeout=15.0)
        # check error
        if r.status_code == 200:
            # parse data
            data_d = r.json()
            json_flyspray_est = dweet_decode(data_d['with'][0]['content']['raw_flyspray_est']).decode('utf8')
            # update redis
            DB.master.set_obj("dweet:flyspray_rss_est", json.loads(json_flyspray_est))
            DB.master.set_ttl("dweet:flyspray_rss_est", ttl=3600)
    except Exception:
        logging.error(traceback.format_exc())


def gsheet_job():
    # https request
    try:
        response = requests.get(gsheet_url, timeout=5.0)
        # process response
        d = dict()
        for line in response.iter_lines(decode_unicode='utf-8'):
            tag, value = line.split(',')
            d[tag] = value
        redis_d = dict(update=datetime.now().isoformat("T"), tags=d)
        # update redis
        DB.master.set_obj("gsheet:grt", redis_d)
        DB.master.set_ttl("gsheet:grt", ttl=3600)
    except Exception:
        logging.error(traceback.format_exc())


def air_quality_atmo_est_job():
    url = 'https://services3.arcgis.com/Is0UwT37raQYl9Jj/arcgis/rest/services/ind_Grand_Est_commune/FeatureServer' \
          '/0/query?where=1%3D1&outFields=date_ech,valeur,source,qualif,couleur,lib_zone,code_zone,type_zone' \
          '&returnGeometry=false&resultRecordCount=48&orderByFields=date_ech%20DESC&outSR=4326&f=json'
    today_dt_date = datetime.today().date()
    # https request
    try:
        r = requests.get(url, timeout=5.0)
        # check error
        if r.status_code == 200:
            # decode json message
            atmo_raw_d = r.json()
            # populate zones dict with receive values
            zones_d = {}
            for record in atmo_raw_d['features']:
                # load record data
                r_lib_zone = record['attributes']['lib_zone']
                r_code_zone = record['attributes']['code_zone']
                r_ts = int(record['attributes']['date_ech'])
                r_dt = datetime.utcfromtimestamp(r_ts / 1000)
                r_value = record['attributes']['valeur']
                # retain today value
                if r_dt.date() == today_dt_date:
                    zones_d[r_code_zone] = r_value
            # create and populate result dict
            d_air_quality = {}
            d_air_quality['nancy'] = zones_d.get(54395, 0)
            d_air_quality['metz'] = zones_d.get(57463, 0)
            d_air_quality['reims'] = zones_d.get(51454, 0)
            d_air_quality['strasbourg'] = zones_d.get(67482, 0)
            # update redis
            DB.master.set_obj('atmo:quality', d_air_quality)
            DB.master.set_ttl('atmo:quality', ttl=3600*4)
    except Exception:
        logging.error(traceback.format_exc())


def vigilance_job():
    try:
        # request XML data from server
        r = requests.get('http://vigilance.meteofrance.com/data/NXFR34_LFPW_.xml', timeout=5.0)
        # check error
        if r.status_code == 200:
            # dom parsing (convert UTF-8 r.text to XML char)
            dom = minidom.parseString(r.text.encode('ascii', 'xmlcharrefreplace'))
            # set dict for dep data
            vig_data = {'update': "", 'department': {}}
            # map build date
            tz = pytz.timezone('Europe/Paris')
            map_date = str(dom.getElementsByTagName('entetevigilance')[0].getAttribute('dateinsert'))
            map_dt = tz.localize(datetime(int(map_date[0:4]), int(map_date[4:6]),
                                          int(map_date[6:8]), int(map_date[8:10]),
                                          int(map_date[10:12])))
            vig_data['update'] = map_dt.isoformat()
            # parse every departments
            for items in dom.getElementsByTagName('datavigilance'):
                # current "department"
                dep_code = str(items.attributes['dep'].value)
                # get risk ID  if exist
                risk_id = []
                for risk in items.getElementsByTagName('risque'):
                    risk_id.append(int(risk.attributes['valeur'].value))
                # get flood ID if exist
                flood_id = None
                for flood in items.getElementsByTagName('crue'):
                    flood_id = int(flood.attributes['valeur'].value)
                # get color ID
                color_id = int(items.attributes['couleur'].value)
                # build vig_data
                vig_data['department'][dep_code] = {'vig_level': color_id,
                                                    'flood_level': flood_id,
                                                    'risk_id': risk_id}
            DB.master.set_obj("weather:vigilance", vig_data)
            DB.master.set_ttl("weather:vigilance", ttl=3600)
    except Exception:
        logging.error(traceback.format_exc())


def local_info_job():
    # do request
    try:
        l_titles = []
        for post in feedparser.parse("https://france3-regions.francetvinfo.fr/societe/rss?r=grand-est").entries:
            l_titles.append(post.title)
        DB.master.set_obj("news:local", l_titles)
        DB.master.set_ttl("news:local", ttl=3600)
    except Exception:
        logging.error(traceback.format_exc())


def twitter_job():
    def tcl_normalize_str(tweet_str):
        tcl_str = ""
        for c in tweet_str:
            if ord(c) < 0xffff:
                tcl_str += c
        return html.unescape(tcl_str)

    try:
        # params
        tw_username = "grtgaz"
        tw_count = 5
        tw_oauth = OAuth1(tw_api_key, tw_api_secret, tw_access_token, tw_access_token_secret)
        # build url
        url = "https://api.twitter.com/1.1/statuses/user_timeline.json?"
        url += "screen_name=%s&count=%i&tweet_mode=extended&exclude_retweets=true"
        url %= (tw_username, tw_count)
        # do request
        r = requests.get(url, auth=tw_oauth, timeout=5.0)
        # check error
        if r.status_code == 200:
            d_tweets = r.json()
            tweets_l = []
            # format all tweet and re-tweet
            for tw in d_tweets:
                # re-tweet
                if tw.get("retweeted_status", None):
                    rt_user = tw["retweeted_status"]["user"]["screen_name"]
                    tweets_l.append(tcl_normalize_str("RT @%s: %s" % (rt_user, tw["retweeted_status"]["full_text"])))
                # tweet
                else:
                    tweets_l.append(tcl_normalize_str(tw["full_text"]))
            # update redis
            d_redis = dict(tweets=tweets_l, update=datetime.now().isoformat("T"))
            DB.master.set_obj("twitter:tweets:grtgaz", d_redis)
            DB.master.set_ttl("twitter:tweets:grtgaz", ttl=1800)
    except Exception:
        logging.error(traceback.format_exc())
        return None


def sport_l1_job():
    # http request
    try:
        r = requests.get("http://m.lfp.fr/ligue1/classement", timeout=5.0)

        if r.status_code == 200:
            od_l1_club = OrderedDict()
            s = BeautifulSoup(r.content, "html.parser")

            # first table on page
            t = s.find_all("table")[0]

            # each row in table
            for row in t.find_all("tr"):
                name = row.find("td", attrs={"class": "club"})
                if name:
                    # club name as dict key
                    name = name.text.strip()
                    od_l1_club[name] = OrderedDict()
                    # find rank
                    od_l1_club[name]['rank'] = row.find("td").text.strip()
                    # find points
                    od_l1_club[name]['pts'] = row.find("td", attrs={"class": "pts"}).text.strip()
                    # find all stats
                    l_td_center = row.find_all("td", attrs={"class": "center"})
                    if l_td_center:
                        od_l1_club[name]["played"] = l_td_center[0].text.strip()
                        od_l1_club[name]["wins"] = l_td_center[1].text.strip()
                        od_l1_club[name]["draws"] = l_td_center[2].text.strip()
                        od_l1_club[name]["loses"] = l_td_center[3].text.strip()
                        od_l1_club[name]["for"] = l_td_center[4].text.strip()
                        od_l1_club[name]["against"] = l_td_center[5].text.strip()
                        od_l1_club[name]["diff"] = l_td_center[6].text.strip()
            DB.master.set_obj("sport:l1", od_l1_club)
            DB.master.set_ttl("sport:l1", ttl=7200)
    except Exception:
        logging.error(traceback.format_exc())
        return None


# main
if __name__ == '__main__':
    # logging setup
    logging.basicConfig(format='%(asctime)s %(message)s')

    # init scheduler
    schedule.every(2).minutes.do(twitter_job)
    schedule.every(4).minutes.do(dweet_job)
    schedule.every(5).minutes.do(local_info_job)
    schedule.every(5).minutes.do(gsheet_job)
    schedule.every(5).minutes.do(vigilance_job)
    schedule.every(60).minutes.do(air_quality_atmo_est_job)
    # first call
    dweet_job()
    gsheet_job()
    air_quality_atmo_est_job()
    vigilance_job()
    local_info_job()
    twitter_job()

    # main loop
    while True:
        schedule.run_pending()
        time.sleep(1)

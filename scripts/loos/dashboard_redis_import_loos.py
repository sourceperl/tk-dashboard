#!/usr/bin/env python3

from collections import OrderedDict
from configparser import ConfigParser
from datetime import datetime, timedelta
import feedparser
import html
import json
import logging
import os
import time
import traceback
from bs4 import BeautifulSoup
import redis
import requests
from requests_oauthlib import OAuth1
import schedule
import pytz
from xml.dom import minidom


# some const
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:2.0.1) Gecko/20100101 Firefox/4.0.1"

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
        DB.master.set_obj("gsheet:grt", redis_d)
        DB.master.set_ttl("gsheet:grt", ttl=3600)
    except Exception:
        logging.error(traceback.format_exc())


def weather_today_job():
    try:
        # request HTML data from server
        r = requests.get("https://weather.com/fr-FR/temps/aujour/l/FRXX6464:1:FR", timeout=5.0, headers={"User-Agent": USER_AGENT})
        # check error
        if r.status_code == 200:
            d_today = {}
            s = BeautifulSoup(r.content, "html.parser")
            # temp current
            try:
                d_today['t'] = int(s.find("div", attrs={"class": "today_nowcard-temp"}).text.strip()[:-1])
            except:
                d_today['t'] = None
            # weather status str
            try:
                d_today['description'] = s.find("div", attrs={"class": "today_nowcard-phrase"}).text.strip().lower()
            except:
                d_today['description'] = 'n/a'
            # temp max/min
            l_span = s.find_all("span", attrs={"class": "deg-hilo-nowcard"})
            try:
                d_today['t_max'] = int(l_span[0].text.strip()[:-1])
            except:
                d_today['t_max'] = d_today['t']
            try:
                d_today['t_min'] = int(l_span[1].text.strip()[:-1])
            except:
                d_today['t_min'] = d_today['t']
            # store to redis
            DB.master.set_obj('weather:today:loos', d_today)
            DB.master.set_ttl('weather:today:loos', ttl=3600)
    except Exception:
        logging.error(traceback.format_exc())


def air_quality_atmo_hdf_job():
    url = 'https://services8.arcgis.com/rxZzohbySMKHTNcy/arcgis/rest/services/ind_hdf_agglo/FeatureServer/0/query' \
          '?where=1%3D1&outFields=date_ech,valeur,source,qualif,couleur,lib_zone,code_zone,type_zone' \
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
            d_air_quality['amiens'] = zones_d.get('80021', 0)
            d_air_quality['lille'] = zones_d.get('59350', 0)
            d_air_quality['dunkerque'] = zones_d.get('59183', 0)
            d_air_quality['valenciennes'] = zones_d.get('59606', 0)
            d_air_quality['maubeuge'] = zones_d.get('59392', 0)
            d_air_quality['saint-quentin'] = zones_d.get('02691', 0)
            # update redis
            DB.master.set_obj('atmo:quality', d_air_quality)
            DB.master.set_ttl('atmo:quality', ttl=3600*4)
    except Exception:
        logging.error(traceback.format_exc())


def openweathermap_forecast_job():
    # https request
    try:
        # build url
        ow_url = "http://api.openweathermap.org/data/2.5/forecast?"
        ow_url += "q=Loos,fr&appid=%s&units=metric&lang=fr" % ow_app_id
        # do request
        ow_d = requests.get(ow_url, timeout=5.0).json()
        # decode json
        t_today = None
        d_days = {}
        for i in range(0, 5):
            d_days[i] = dict(t_min=50.0, t_max=-50.0, main='', description='', icon='')
        # parse json
        for item in ow_d["list"]:
            # for day-0 to day-4
            for i_day in range(5):
                txt_date, txt_time = item['dt_txt'].split(' ')
                # search today
                if txt_date == (datetime.now() + timedelta(days=i_day)).date().strftime('%Y-%m-%d'):
                    # search min/max temp
                    d_days[i_day]['t_min'] = min(d_days[i_day]['t_min'], item['main']['temp_min'])
                    d_days[i_day]['t_max'] = max(d_days[i_day]['t_max'], item['main']['temp_max'])
                    # main and icon in 12h item
                    if txt_time == '12:00:00' or t_today is None:
                        d_days[i_day]['main'] = item['weather'][0]['main']
                        d_days[i_day]['icon'] = item['weather'][0]['icon']
                        d_days[i_day]['description'] = item['weather'][0]['description']
                        if t_today is None:
                            t_today = item['main']['temp']
                            d_days[0]['t'] = t_today
        # store to redis
        DB.master.set_obj('weather:forecast:loos', d_days)
        DB.master.set_ttl('weather:forecast:loos', ttl=3600)
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
        for post in feedparser.parse("https://france3-regions.francetvinfo.fr/societe/rss?r=hauts-de-france").entries:
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
    schedule.every(5).minutes.do(local_info_job)
    schedule.every(5).minutes.do(gsheet_job)
    schedule.every(5).minutes.do(weather_today_job)
    schedule.every(5).minutes.do(vigilance_job)
    schedule.every(15).minutes.do(openweathermap_forecast_job)
    schedule.every(60).minutes.do(air_quality_atmo_hdf_job)
    # first call
    gsheet_job()
    weather_today_job()
    air_quality_atmo_hdf_job()
    openweathermap_forecast_job()
    vigilance_job()
    local_info_job()
    twitter_job()

    # main loop
    while True:
        schedule.run_pending()
        time.sleep(1)

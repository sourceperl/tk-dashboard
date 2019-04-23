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
# iswip
iswip_url = cnf.get('iswip', 'url')
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
    # define class
    class AtmoHdfBeautifulSoup(BeautifulSoup):
        def find_ville_id(self, ville_id):
            try:
                str_ssindice = '{"indice": "france", "periode": "ajd", "ville_id": "%i"}' % ville_id
                idx = int(self.find("div", attrs={"data-ssindice": str_ssindice}).find("span").text.strip())
            except (AttributeError, ValueError):
                idx = 0
            return idx
    # https request
    try:
        r = requests.get("http://www.atmo-hdf.fr/", timeout=5.0)
        # check error
        if r.status_code == 200:
            d_air_quality = {}
            bs = AtmoHdfBeautifulSoup(r.content, "html.parser")
            # search today index for some ids
            d_air_quality["amiens"] = bs.find_ville_id(3)
            d_air_quality["lille"] = bs.find_ville_id(13)
            d_air_quality["dunkerque"] = bs.find_ville_id(19)
            d_air_quality["valenciennes"] = bs.find_ville_id(22)
            d_air_quality["maubeuge"] = bs.find_ville_id(16)
            d_air_quality["saint-quentin"] = bs.find_ville_id(109)
            # update redis
            DB.master.set_obj("atmo:quality", d_air_quality)
            DB.master.set_ttl("atmo:quality", ttl=3600)
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


def iswip_job():
    try:
        # do request
        devices_l = requests.get(iswip_url, timeout=5.0).json()
        d_dev = {}
        for device in devices_l:
            # device id
            dev_id = str(device['device_description']).replace(' ', '_')
            # device message
            dev_msg = ''
            for token in device['lastmessage_content'].split(';'):
                name, value = token.split('=')
                if name == 'TypeMessage':
                    dev_msg = value
            # update redis
            d_dev[dev_id] = dev_msg
        DB.master.set_obj('iswip:room_status', d_dev)
        DB.master.set_ttl('iswip:room_status', ttl=3600)
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


# deprecated
# def gmap_travel_time_job():
#     try:
#         d_traffic = {}
#         for gm_dest in ("Arras", "Amiens", "Dunkerque", "Maubeuge", "Reims"):
#             # build url
#             gm_url_origin = urllib.parse.quote_plus(gmap_origin)
#             gm_url_destination = urllib.parse.quote_plus(gm_dest)
#             gm_url = "https://maps.googleapis.com/maps/api/directions/json"
#             gm_url += "?&origin=%s&destination=%s&departure_time=now&key=%s"
#             gm_url %= gm_url_origin, gm_url_destination, gmap_key
#             # http request
#             gm_json = requests.get(gm_url, timeout=5.0).json()
#             # decode json
#             duration_abs = gm_json["routes"][0]["legs"][0]["duration"]["value"]
#             duration_with_traffic = gm_json["routes"][0]["legs"][0]["duration_in_traffic"]["value"]
#             d_traffic[gm_dest] = dict(duration=duration_abs, duration_traffic=duration_with_traffic)
#         DS.redis_set_obj('gmap:traffic', d_traffic)
#         DS.redis_set_ttl('gmap:traffic', ttl=1800)
#     except Exception:
#         logging.error(traceback.format_exc())


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
    schedule.every(1).minute.do(iswip_job)
    schedule.every(2).minutes.do(twitter_job)
    schedule.every(5).minutes.do(local_info_job)
    schedule.every(5).minutes.do(gsheet_job)
    schedule.every(5).minutes.do(weather_today_job)
    schedule.every(5).minutes.do(vigilance_job)
    schedule.every(15).minutes.do(air_quality_atmo_hdf_job)
    schedule.every(15).minutes.do(openweathermap_forecast_job)
    # first call
    gsheet_job()
    weather_today_job()
    air_quality_atmo_hdf_job()
    openweathermap_forecast_job()
    vigilance_job()
    local_info_job()
    iswip_job()
    twitter_job()

    # main loop
    while True:
        schedule.run_pending()
        time.sleep(1)

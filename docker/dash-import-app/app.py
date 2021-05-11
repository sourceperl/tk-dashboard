#!/usr/bin/env python3

from collections import Counter
from configparser import ConfigParser
from datetime import datetime, timedelta
import urllib.parse
import feedparser
import html
import json
import logging
import io
import re
import time
import traceback
from xml.dom import minidom
import redis
import requests
from requests_oauthlib import OAuth1
import schedule
import PIL.Image
from wordcloud import WordCloud
from metar.Metar import Metar
import pytz

# some const
USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64; rv:2.0.1) Gecko/20100101 Firefox/4.0.1'

# read config
cnf = ConfigParser()
cnf.read('/data/dashboard-conf-vol/dashboard.conf')
# gmap img traffic
gmap_img_url = cnf.get('gmap_img', 'img_url')
# gsheet
gsheet_url = cnf.get('gsheet', 'url')
# openweathermap
ow_app_id = cnf.get('openweathermap', 'app_id')
# twitter
tw_api_key = cnf.get('twitter', 'api_key')
tw_api_secret = cnf.get('twitter', 'api_secret')
tw_access_token = cnf.get('twitter', 'access_token')
tw_access_token_secret = cnf.get('twitter', 'access_token_secret')


# some functions
def dt_utc_to_local(utc_dt):
    now_ts = time.time()
    offset = datetime.fromtimestamp(now_ts) - datetime.utcfromtimestamp(now_ts)
    return utc_dt + offset


# some class
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
    master = CustomRedis(host='dash-redis-srv', socket_timeout=4, socket_keepalive=True)


# some function
def air_quality_atmo_hdf_job():
    url = 'https://services8.arcgis.com/' + \
          'rxZzohbySMKHTNcy/arcgis/rest/services/ind_hdf_3j/FeatureServer/0/query' + \
          '?where=%s' % urllib.parse.quote('code_zone IN (02691, 59183, 59350, 59392, 59606, 80021)') + \
          '&outFields=date_ech, code_qual, lib_qual, lib_zone, code_zone' + \
          '&returnGeometry=false&resultRecordCount=48' + \
          '&orderByFields=%s&f=json' % urllib.parse.quote('date_ech DESC')
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
                r_code_zone = record['attributes']['code_zone']
                r_ts = int(record['attributes']['date_ech'])
                r_dt = datetime.utcfromtimestamp(r_ts / 1000)
                r_value = record['attributes']['code_qual']
                # retain today value
                if r_dt.date() == today_dt_date:
                    zones_d[r_code_zone] = r_value
            # skip key publish if zones_d is empty
            if not zones_d:
                raise ValueError('dataset is empty')
            # create and populate result dict
            d_air_quality = {'amiens': zones_d.get('80021', 0),
                             'dunkerque': zones_d.get('59183', 0),
                             'lille': zones_d.get('59350', 0),
                             'maubeuge': zones_d.get('59392', 0),
                             'saint-quentin': zones_d.get('02691', 0),
                             'valenciennes': zones_d.get('59606', 0)}
            # update redis
            DB.master.set_to_json('atmo:quality', d_air_quality)
            DB.master.set_ttl('atmo:quality', ttl=6 * 3600)
    except Exception:
        logging.error(traceback.format_exc())


def gsheet_job():
    # https request
    try:
        response = requests.get(gsheet_url, timeout=5.0)
        # process response
        d = dict()
        for line in response.iter_lines(decode_unicode=True):
            tag, value = line.split(',')
            d[tag] = value
        redis_d = dict(update=datetime.now().isoformat('T'), tags=d)
        DB.master.set_to_json('gsheet:grt', redis_d)
        DB.master.set_ttl('gsheet:grt', ttl=2 * 3600)
    except Exception:
        logging.error(traceback.format_exc())


def img_gmap_traffic_job():
    # http request
    try:
        r = requests.get(gmap_img_url, stream=True, timeout=5.0)
        if r.status_code == 200:
            # convert RAW img format (bytes) to Pillow image
            pil_img = PIL.Image.open(io.BytesIO(r.raw.read()))
            # crop image
            pil_img = pil_img.crop((0, 0, 560, 328))
            #pil_img.thumbnail([632, 328])
            img_io = io.BytesIO()
            pil_img.save(img_io, format='PNG')
            # store RAW PNG to redis key
            DB.master.set_bytes('img:traffic-map:png', img_io.getvalue())
            DB.master.set_ttl('img:traffic-map:png', 2 * 3600)
    except Exception:
        logging.error(traceback.format_exc())


def img_grt_tw_cloud_job():
    def is_camelcase(s):
        return s != s.lower() and '_' not in s

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
                DB.master.set_ttl('img:grt-tweet-wordcloud:png', 2 * 3600)
    except Exception:
        logging.error(traceback.format_exc())


def local_info_job():
    # do request
    try:
        l_titles = []
        for post in feedparser.parse('https://france3-regions.francetvinfo.fr/societe/rss?r=hauts-de-france').entries:
            l_titles.append(post.title)
        DB.master.set_to_json('news:local', l_titles)
        DB.master.set_ttl('news:local', ttl=2 * 3600)
    except Exception:
        logging.error(traceback.format_exc())


def openweathermap_forecast_job():
    # https request
    try:
        # build url
        ow_url = 'http://api.openweathermap.org/data/2.5/forecast?'
        ow_url += 'q=Loos,fr&appid=%s&units=metric&lang=fr' % ow_app_id
        # do request
        ow_d = requests.get(ow_url, timeout=5.0).json()
        # decode json
        t_today = None
        d_days = {}
        for i in range(0, 5):
            d_days[i] = dict(t_min=50.0, t_max=-50.0, main='', description='', icon='')
        # parse json
        for item in ow_d['list']:
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
        DB.master.set_to_json('weather:forecast:loos', d_days)
        DB.master.set_ttl('weather:forecast:loos', ttl=2 * 3600)
    except Exception:
        logging.error(traceback.format_exc())


def twitter_job():
    def tcl_normalize_str(tweet_str):
        tcl_str = ''
        for c in tweet_str:
            if ord(c) < 0xffff:
                tcl_str += c
        return html.unescape(tcl_str)

    try:
        # params
        tw_username = 'grtgaz'
        tw_count = 5
        tw_oauth = OAuth1(tw_api_key, tw_api_secret, tw_access_token, tw_access_token_secret)
        # build url
        url = 'https://api.twitter.com/1.1/statuses/user_timeline.json?'
        url += 'screen_name=%s&count=%i&tweet_mode=extended&exclude_retweets=true'
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
                if tw.get('retweeted_status', None):
                    rt_user = tw['retweeted_status']['user']['screen_name']
                    tweets_l.append(tcl_normalize_str('RT @%s: %s' % (rt_user, tw['retweeted_status']['full_text'])))
                # tweet
                else:
                    tweets_l.append(tcl_normalize_str(tw['full_text']))
            # update redis
            d_redis = dict(tweets=tweets_l, update=datetime.now().isoformat('T'))
            DB.master.set_to_json('twitter:tweets:grtgaz', d_redis)
            DB.master.set_ttl('twitter:tweets:grtgaz', ttl=3600)
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
            vig_data = {'update': '', 'department': {}}
            # map build date
            tz = pytz.timezone('Europe/Paris')
            map_date = str(dom.getElementsByTagName('entetevigilance')[0].getAttribute('dateinsert'))
            map_dt = tz.localize(datetime(int(map_date[0:4]), int(map_date[4:6]),
                                          int(map_date[6:8]), int(map_date[8:10]),
                                          int(map_date[10:12])))
            vig_data['update'] = map_dt.isoformat()
            # parse every departments
            for items in dom.getElementsByTagName('datavigilance'):
                # current department
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
            DB.master.set_to_json('weather:vigilance', vig_data)
            DB.master.set_ttl('weather:vigilance', ttl=2 * 3600)
    except Exception:
        logging.error(traceback.format_exc())


def weather_today_job():
    try:
        # request data from NOAA server (METAR of Lille-Lesquin Airport)
        r = requests.get('http://tgftp.nws.noaa.gov/data/observations/metar/stations/LFQQ.TXT',
                         timeout=5.0, headers={'User-Agent': USER_AGENT})
        # check error
        if r.status_code == 200:
            # extract METAR message
            metar_msg = r.content.decode().split('\n')[1]
            # METAR parse
            obs = Metar(metar_msg)
            # init and populate d_today dict
            d_today = {}
            # message date and time
            if obs.time:
                d_today['update_iso'] = obs.time.strftime('%Y-%m-%dT%H:%M:%SZ')
                d_today['update_fr'] = dt_utc_to_local(obs.time).strftime('%H:%M %d/%m')
            # current temperature
            if obs.temp:
                d_today['temp'] = round(obs.temp.value('C'))
            # current dew point
            if obs.dewpt:
                d_today['dewpt'] = round(obs.dewpt.value('C'))
            # current pressure
            if obs.press:
                d_today['press'] = round(obs.press.value('hpa'))
            # current wind speed
            if obs.wind_speed:
                d_today['w_speed'] = round(obs.wind_speed.value('KMH'))
            # current wind gust
            if obs.wind_gust:
                d_today['w_gust'] = round(obs.wind_gust.value('KMH'))
            # current wind direction
            if obs.wind_dir:
                # replace 'W'est by 'O'uest
                d_today['w_dir'] = obs.wind_dir.compass().replace('W', 'O')
            # weather status str
            d_today['descr'] = 'n/a'
            # store to redis
            DB.master.set_to_json('weather:today:loos', d_today)
            DB.master.set_ttl('weather:today:loos', ttl=2 * 3600)
    except Exception:
        logging.error(traceback.format_exc())


# main
if __name__ == '__main__':
    # logging setup
    logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)
    logging.info('dash-import-app started')

    # init scheduler
    schedule.every(60).minutes.do(air_quality_atmo_hdf_job)
    schedule.every(5).minutes.do(gsheet_job)
    schedule.every(2).minutes.do(img_gmap_traffic_job)
    schedule.every(30).minutes.do(img_grt_tw_cloud_job)
    schedule.every(5).minutes.do(local_info_job)
    schedule.every(15).minutes.do(openweathermap_forecast_job)
    schedule.every(5).minutes.do(twitter_job)
    schedule.every(5).minutes.do(vigilance_job)
    schedule.every(5).minutes.do(weather_today_job)
    # first call
    air_quality_atmo_hdf_job()
    gsheet_job()
    img_gmap_traffic_job()
    img_grt_tw_cloud_job()
    local_info_job()
    openweathermap_forecast_job()
    twitter_job()
    vigilance_job()
    weather_today_job()

    # main loop
    while True:
        schedule.run_pending()
        time.sleep(1)
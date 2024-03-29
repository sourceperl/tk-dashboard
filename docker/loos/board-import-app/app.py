#!/usr/bin/env python3

from collections import Counter
from configparser import ConfigParser
from datetime import datetime, timedelta
import urllib.parse
import hashlib
import html
import io
import json
import logging
import os
import re
import time
from xml.dom import minidom
import feedparser
import requests
from requests_oauthlib import OAuth1
import schedule
import PIL.Image
from wordcloud import WordCloud
from metar.Metar import Metar
import pytz
import pdf2image
import PIL.Image
import PIL.ImageDraw
from board_lib import CustomRedis, catch_log_except, dt_utc_to_local
from webdav import WebDAV


# some const
USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64; rv:2.0.1) Gecko/20100101 Firefox/4.0.1'

# some var
owc_doc_dir_last_sync = 0
owc_car_dir_last_sync = 0

# read config
cnf = ConfigParser()
cnf.read('/data/conf/board.conf')
# redis
redis_user = cnf.get('redis', 'user')
redis_pass = cnf.get('redis', 'pass')
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
# webdav
webdav_url = cnf.get('owncloud_dashboard', 'webdav_url')
webdav_user = cnf.get('owncloud_dashboard', 'webdav_user')
webdav_pass = cnf.get('owncloud_dashboard', 'webdav_pass')
webdav_reglement_doc_dir = cnf.get('owncloud_dashboard', 'webdav_reglement_doc_dir')
webdav_carousel_img_dir = cnf.get('owncloud_dashboard', 'webdav_carousel_img_dir')


# some class
class DB:
    # create connector
    main = CustomRedis(host='board-redis-srv', username=redis_user, password=redis_pass,
                       socket_timeout=4, socket_keepalive=True)
    bridge = CustomRedis(host='board-redis-cli-bridge-int', socket_timeout=4, socket_keepalive=True)


# some function
@catch_log_except()
def air_quality_atmo_hdf_job():
    url = 'https://services8.arcgis.com/' + \
          'rxZzohbySMKHTNcy/arcgis/rest/services/ind_hdf_3j/FeatureServer/0/query' + \
          '?where=%s' % urllib.parse.quote('code_zone IN (02691, 59183, 59350, 59392, 59606, 80021)') + \
          '&outFields=date_ech, code_qual, lib_qual, lib_zone, code_zone' + \
          '&returnGeometry=false&resultRecordCount=48' + \
          '&orderByFields=%s&f=json' % urllib.parse.quote('date_ech DESC')
    today_dt_date = datetime.today().date()
    # https request
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
        DB.main.set_as_json('json:atmo', d_air_quality, ex=6 * 3600)


@catch_log_except()
def bridge_job():
    # relay flyspray data from bridge to main DB
    fly_data_nord = DB.bridge.get_from_json('rx:bur:flyspray_rss_nord')
    fly_data_est = DB.bridge.get_from_json('rx:bur:flyspray_rss_est')
    if fly_data_nord:
        DB.main.set_as_json('json:flyspray-nord', fly_data_nord, ex=1 * 3600)
    if fly_data_est:
        DB.main.set_as_json('json:flyspray-est', fly_data_est, ex=1 * 3600)


@catch_log_except()
def gsheet_job():
    # https request
    response = requests.get(gsheet_url, timeout=5.0)
    # process response
    d = dict()
    for line in response.iter_lines(decode_unicode=True):
        tag, value = line.split(',')
        d[tag] = value
    redis_d = dict(update=datetime.now().isoformat('T'), tags=d)
    DB.main.set_as_json('json:gsheet', redis_d, ex=2 * 3600)


@catch_log_except()
def img_gmap_traffic_job():
    # http request
    r = requests.get(gmap_img_url, stream=True, timeout=5.0)
    if r.status_code == 200:
        # convert RAW img format (bytes) to Pillow image
        pil_img = PIL.Image.open(io.BytesIO(r.raw.read()))
        # crop image
        pil_img = pil_img.crop((0, 0, 560, 328))
        # pil_img.thumbnail([632, 328])
        img_io = io.BytesIO()
        pil_img.save(img_io, format='PNG')
        # store RAW PNG to redis key
        DB.main.set('img:traffic-map:png', img_io.getvalue(), ex=2 * 3600)


@catch_log_except()
def img_grt_tw_cloud_job():
    def is_camelcase(s):
        return s != s.lower() and '_' not in s

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
            DB.main.set('img:grt-twitter-cloud:png', img_io.getvalue(), ex=2 * 3600)


@catch_log_except()
def local_info_job():
    # do request
    l_titles = []
    for post in feedparser.parse('https://france3-regions.francetvinfo.fr/societe/rss?r=hauts-de-france').entries:
        title = post.title
        title = title.strip()
        title = title.replace('\n', ' ')
        l_titles.append(title)
    DB.main.set_as_json('json:news', l_titles, ex=2 * 3600)


@catch_log_except()
def openweathermap_forecast_job():
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
    DB.main.set_as_json('json:weather:forecast:loos', d_days, ex=2 * 3600)


@catch_log_except()
def owc_updated_job():
    # check if the owncloud directories has been updated by users (start sync jobs if need)
    global owc_doc_dir_last_sync, owc_car_dir_last_sync

    for f in wdv.ls():
        item = f['file_path']
        item_last_modified = int(f['dt_last_modified'].timestamp())
        # document update ?
        if item == webdav_reglement_doc_dir:
            # update need
            if item_last_modified > owc_doc_dir_last_sync:
                logging.debug(f'"{webdav_reglement_doc_dir}" seem updated: run "owncloud_sync_doc_job"')
                owc_sync_doc_job()
                owc_doc_dir_last_sync = item_last_modified
        # carousel update ?
        elif item == webdav_carousel_img_dir:
            # update need
            if item_last_modified > owc_car_dir_last_sync:
                logging.debug(f'"{webdav_carousel_img_dir}" seem updated: run "owncloud_sync_carousel_job"')
                owc_sync_carousel_job()
                owc_car_dir_last_sync = item_last_modified


@catch_log_except()
def owc_sync_carousel_job():
    # sync owncloud carousel directory with local
    # local constants
    DIR_CAR_INFOS = 'dir:carousel:infos'
    DIR_CAR_RAW = 'dir:carousel:raw:min-png'

    # local functions
    def update_carousel_raw_data(filename, raw_data):
        # build json infos record
        md5 = hashlib.md5(raw_data).hexdigest()
        js_infos = json.dumps(dict(size=len(raw_data), md5=md5))
        # convert raw data to PNG thumbnails
        # create default error image
        img_to_redis = PIL.Image.new('RGB', (655, 453), (255, 255, 255))
        draw = PIL.ImageDraw.Draw(img_to_redis)
        draw.text((0, 0), f'loading error (src: "{filename}")', (0, 0, 0))
        # replace default image by convert result
        try:
            # convert png and jpg file
            if filename.lower().endswith('.png') or filename.lower().endswith('.jpg'):
                # image to PIL
                img_to_redis = PIL.Image.open(io.BytesIO(raw_data))
            # convert pdf file
            elif filename.lower().endswith('.pdf'):
                # PDF to PIL: convert first page to PIL image
                img_to_redis = pdf2image.convert_from_bytes(raw_data)[0]
        except Exception:
            pass
        # resize and format as raw png
        img_to_redis.thumbnail([655, 453])
        io_to_redis = io.BytesIO()
        img_to_redis.save(io_to_redis, format='PNG')
        # redis add  (atomic write)
        pipe = DB.main.pipeline()
        pipe.hset(DIR_CAR_INFOS, filename, js_infos)
        pipe.hset(DIR_CAR_RAW, filename, io_to_redis.getvalue())
        pipe.execute()

    # log sync start
    logging.info('start of sync for owncloud carousel')
    # list local redis files
    local_files_d = {}
    for f_name, js_infos in DB.main.hgetall(DIR_CAR_INFOS).items():
        try:
            filename = f_name.decode()
            size = json.loads(js_infos)['size']
            local_files_d[filename] = size
        except ValueError:
            pass
    # check "dir:carousel:raw:min-png" consistency
    raw_file_l = [f.decode() for f in DB.main.hkeys(DIR_CAR_RAW)]
    # remove orphan infos record
    for f in list(set(local_files_d) - set(raw_file_l)):
        logging.debug(f'remove orphan "{f}" record in hash "{DIR_CAR_INFOS}"')
        DB.main.hdel(DIR_CAR_INFOS, f)
        del local_files_d[f]
    # remove orphan raw-png record
    for f in list(set(raw_file_l) - set(local_files_d)):
        logging.debug(f'remove orphan "{f}" record in hash "{DIR_CAR_RAW}"')
        DB.main.hdel(DIR_CAR_RAW, f)
    # list owncloud files (disallow directory)
    own_files_d = {}
    for f_d in wdv.ls(webdav_carousel_img_dir):
        file_path = f_d['file_path']
        size = f_d['content_length']
        if file_path and not file_path.endswith('/'):
            # search site only tags (_@loos_, _@messein_...) in filename
            # site id is 16 chars max
            site_tag_l = re.findall(r'_@([a-zA-Z0-9\-]{1,16})', file_path)
            site_tag_l = [s.strip().lower() for s in site_tag_l]
            site_tag_ok = 'loos' in site_tag_l or not site_tag_l
            # download filter: ignore txt file or heavy fie (>10 MB)
            filter_ok = not file_path.lower().endswith('.txt') \
                        and (size < 10 * 1024 * 1024) \
                        and site_tag_ok
            # add file to owncloud dict
            if filter_ok:
                own_files_d[f_d['file_path']] = size
    # exist only on local redis
    for f in list(set(local_files_d) - set(own_files_d)):
        logging.info(f'"{f}" exist only on local -> remove it')
        # redis remove (atomic)
        pipe = DB.main.pipeline()
        pipe.hdel(DIR_CAR_INFOS, f)
        pipe.hdel(DIR_CAR_RAW, f)
        pipe.execute()
    # exist only on remote owncloud
    for f in list(set(own_files_d) - set(local_files_d)):
        logging.info('"%s" exist only on remote -> download it' % f)
        data = wdv.download(os.path.join(webdav_carousel_img_dir, f))
        if data:
            update_carousel_raw_data(f, data)
    # exist at both side (update only if file size change)
    for f in list(set(local_files_d).intersection(own_files_d)):
        local_size = local_files_d[f]
        remote_size = own_files_d[f]
        logging.debug(f'check "{f}" remote size [{remote_size}]/local size [{local_size}]')
        if local_size != remote_size:
            logging.info(f'"{f}" size mismatch -> download it')
            data = wdv.download(os.path.join(webdav_carousel_img_dir, f))
            if data:
                update_carousel_raw_data(f, data)
    # log sync end
    logging.info('end of sync for owncloud carousel')


@catch_log_except()
def owc_sync_doc_job():
    # sync owncloud document directory with local
    # local constants
    DIR_DOC_INFOS = 'dir:doc:infos'
    DIR_DOC_RAW = 'dir:doc:raw'

    # local functions
    def update_doc_raw_data(filename, raw_data):
        # build json infos record
        md5 = hashlib.md5(raw_data).hexdigest()
        js_infos = json.dumps(dict(size=len(raw_data), md5=md5))
        # redis add  (atomic write)
        pipe = DB.main.pipeline()
        pipe.hset(DIR_DOC_INFOS, filename, js_infos)
        pipe.hset(DIR_DOC_RAW, filename, raw_data)
        pipe.execute()

    # log sync start
    logging.info('start of sync for owncloud doc')
    # list local redis files
    local_files_d = {}
    for f_name, js_infos in DB.main.hgetall(DIR_DOC_INFOS).items():
        try:
            filename = f_name.decode()
            size = json.loads(js_infos)['size']
            local_files_d[filename] = size
        except ValueError:
            pass
    # check "dir:doc:raw:min-png" consistency
    raw_file_l = [f.decode() for f in DB.main.hkeys(DIR_DOC_RAW)]
    # remove orphan infos record
    for f in list(set(local_files_d) - set(raw_file_l)):
        logging.debug(f'remove orphan "{f}" record in hash "{DIR_DOC_INFOS}"')
        DB.main.hdel(DIR_DOC_INFOS, f)
        del local_files_d[f]
    # remove orphan raw-png record
    for f in list(set(raw_file_l) - set(local_files_d)):
        logging.debug(f'remove orphan "{f}" record in hash "{DIR_DOC_RAW}"')
        DB.main.hdel(DIR_DOC_RAW, f)
    # list owncloud files (disallow directory)
    own_files_d = {}
    for f_d in wdv.ls(webdav_reglement_doc_dir):
        file_path = f_d['file_path']
        size = f_d['content_length']
        if file_path and not file_path.endswith('/'):
            # download filter: ignore txt file or heavy fie (>10 MB)
            ok_load = not file_path.lower().endswith('.txt') \
                      and (size < 10 * 1024 * 1024)
            if ok_load:
                own_files_d[f_d['file_path']] = size
    # exist only on local redis
    for f in list(set(local_files_d) - set(own_files_d)):
        logging.info(f'"{f}" exist only on local -> remove it')
        # redis remove (atomic)
        pipe = DB.main.pipeline()
        pipe.hdel(DIR_DOC_INFOS, f)
        pipe.hdel(DIR_DOC_RAW, f)
        pipe.execute()
    # exist only on remote owncloud
    for f in list(set(own_files_d) - set(local_files_d)):
        logging.info(f'"{f}" exist only on remote -> download it')
        data = wdv.download(os.path.join(webdav_reglement_doc_dir, f))
        if data:
            update_doc_raw_data(f, data)
    # exist at both side (update only if file size change)
    for f in list(set(local_files_d).intersection(own_files_d)):
        local_size = local_files_d[f]
        remote_size = own_files_d[f]
        logging.debug(f'check "{f}" remote size [{remote_size}]/local size [{local_size}]')
        if local_size != remote_size:
            logging.info(f'"{f}" size mismatch -> download it')
            data = wdv.download(os.path.join(webdav_reglement_doc_dir, f))
            if data:
                update_doc_raw_data(f, data)
    # log sync end
    logging.info('end of sync for owncloud doc')


@catch_log_except()
def twitter_job():
    def tcl_normalize_str(tweet_str):
        tcl_str = ''
        for c in tweet_str:
            if ord(c) < 0xffff:
                tcl_str += c
        return html.unescape(tcl_str)

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
        DB.main.set_as_json('json:tweets:@grtgaz', d_redis, ex=3600)


@catch_log_except()
def vigilance_job():
    # request XML data from server
    r = requests.get('http://vigilance.meteofrance.com/data/NXFR34_LFPW_.xml', timeout=10.0)
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
        DB.main.set_as_json('json:vigilance', vig_data, ex=2 * 3600)


@catch_log_except()
def weather_today_job():
    # request data from NOAA server (METAR of Lille-Lesquin Airport)
    r = requests.get('http://tgftp.nws.noaa.gov/data/observations/metar/stations/LFQQ.TXT',
                     timeout=10.0, headers={'User-Agent': USER_AGENT})
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
        DB.main.set_as_json('json:weather:today:loos', d_today, ex=2 * 3600)


# main
if __name__ == '__main__':
    # logging setup
    logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)
    logging.getLogger('PIL').setLevel(logging.INFO)
    logging.info('board-import-app started')

    # init webdav client
    wdv = WebDAV(webdav_url, username=webdav_user, password=webdav_pass)

    # init scheduler
    schedule.every(5).minutes.do(owc_updated_job)
    schedule.every(1).hours.do(owc_sync_carousel_job)
    schedule.every(1).hours.do(owc_sync_doc_job)
    schedule.every(60).minutes.do(air_quality_atmo_hdf_job)
    schedule.every(2).minutes.do(bridge_job)
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
    bridge_job()
    gsheet_job()
    img_gmap_traffic_job()
    img_grt_tw_cloud_job()
    local_info_job()
    openweathermap_forecast_job()
    twitter_job()
    vigilance_job()
    weather_today_job()
    owc_updated_job()

    # main loop
    while True:
        schedule.run_pending()
        time.sleep(1)

#!/usr/bin/env python3

import tkinter as tk
from tkinter import ttk
from configparser import ConfigParser
import logging
import time
import threading
from board_hmi_lib import CustomRedis, Tag, Tab, PdfTab, Colors, Geometry
from board_hmi_lib import AirQualityTile, ClockTile, DaysAccTileLoos, GaugeTile, \
                          MessageTile, NewsBannerTile, TwitterTile, FlysprayTile, \
                          ImageRawTile, ImageRawCarouselTile, VigilanceTile, WattsTile, WeatherTile


# read config
cnf = ConfigParser()
cnf.read('/etc/opt/tk-dashboard/board.conf')
# redis
redis_user = cnf.get('redis', 'user')
redis_pass = cnf.get('redis', 'pass')


class DB:
    # create connector
    main = CustomRedis(host='localhost', username=redis_user, password=redis_pass,
                       socket_timeout=4, socket_keepalive=True)


class Tags:
    # create all tag here
    # WARNs: -> all tag are manage by an IO thread
    #        -> tag subscriber callback code are call by IO thread (not by tkinter main thread)
    D_GSHEET_GRT = Tag(get_cmd=lambda: DB.main.get_from_json('json:gsheet'), io_refresh=2.0)
    D_ATMO_QUALITY = Tag(get_cmd=lambda: DB.main.get_from_json('json:atmo'), io_refresh=2.0)
    D_W_TODAY_LOOS = Tag(get_cmd=lambda: DB.main.get_from_json('json:weather:today:loos'), io_refresh=2.0)
    D_W_FORECAST_LOOS = Tag(get_cmd=lambda: DB.main.get_from_json('json:weather:forecast:loos'), io_refresh=2.0)
    D_WEATHER_VIG = Tag(get_cmd=lambda: DB.main.get_from_json('json:vigilance'), io_refresh=2.0)
    D_NEWS_LOCAL = Tag(get_cmd=lambda: DB.main.get_from_json('json:news'), io_refresh=2.0)
    D_TWEETS_GRT = Tag(get_cmd=lambda: DB.main.get_from_json('json:tweets:@grtgaz'), io_refresh=2.0)
    MET_PWR_ACT = Tag(get_cmd=lambda: DB.main.get_from_json('int:loos_elec:pwr_act'), io_refresh=1.0)
    MET_TODAY_WH = Tag(get_cmd=lambda: DB.main.get_from_json('float:loos_elec:today_wh'), io_refresh=2.0)
    MET_YESTERDAY_WH = Tag(get_cmd=lambda: DB.main.get_from_json('float:loos_elec:yesterday_wh'), io_refresh=2.0)
    L_FLYSPRAY_RSS = Tag(get_cmd=lambda: DB.main.get_from_json('json:flyspray-nord'), io_refresh=2.0)
    IMG_ATMO_HDF = Tag(get_cmd=lambda: DB.main.get('img:static:logo-atmo-hdf:png'), io_refresh=10.0)
    IMG_LOGO_GRT = Tag(get_cmd=lambda: DB.main.get('img:static:logo-grt:png'), io_refresh=10.0)
    IMG_GRT_CLOUD = Tag(get_cmd=lambda: DB.main.get('img:grt-twitter-cloud:png'), io_refresh=10.0)
    IMG_TRAFFIC_MAP = Tag(get_cmd=lambda: DB.main.get('img:traffic-map:png'), io_refresh=10.0)
    DIR_CAROUSEL_RAW = Tag(get_cmd=lambda: DB.main.hgetall('dir:carousel:raw:min-png'), io_refresh=10.0)
    DIR_PDF_DOC_LIST= Tag(get_cmd=lambda: map(bytes.decode, DB.main.hkeys('dir:doc:raw')))
    RAW_PDF_DOC_CONTENT = Tag(get_cmd=lambda file: DB.main.hget('dir:doc:raw', file))

    @classmethod
    def init(cls):
        # start IO thread
        threading.Thread(target=cls._io_thread, daemon=True).start()

    @classmethod
    def _io_thread(cls):
        # for non-blocking tag auto-update method (avoid GUI hang when IO delay occur)
        while True:
            for name, tag in cls.__dict__.items():
                # if Tags attribute is a Tag refresh it (with cmd_src func)
                if not name.startswith('__') and isinstance(tag, Tag):
                    tag.io_update(ref=name)
            time.sleep(1.0)


class MainApp(tk.Tk):
    def __init__(self, *args, **kwargs):
        tk.Tk.__init__(self, *args, **kwargs)
        # public
        self.user_idle_timeout = 120000
        # private
        self._idle_timer = None
        # tk stuff
        # remove mouse icon for a dashboard
        self.config(cursor='none')
        # define style to fix size of tab header
        self.style = ttk.Style()
        self.style.theme_settings('default',
                                  {'TNotebook.Tab': {'configure': {'padding': [Geometry.TAB_PAD_WIDTH,
                                                                               Geometry.TAB_PAD_HEIGHT]}}})
        # define notebook
        self.note = ttk.Notebook(self)
        self.tab1 = LiveTab(self.note)
        self.tab2 = PdfTab(self.note, list_tag=Tags.DIR_PDF_DOC_LIST, raw_tag=Tags.RAW_PDF_DOC_CONTENT)
        self.note.add(self.tab1, text='Tableau de bord')
        self.note.add(self.tab2, text='Affichage réglementaire')
        self.note.pack()
        # default tab
        self.note.select(self.tab1)
        # press Esc to quit
        self.bind('<Escape>', lambda e: self.destroy())
        # bind function keys to tabs
        self.bind('<F1>', lambda evt: self.note.select(self.tab1))
        self.bind('<F2>', lambda evt: self.note.select(self.tab2))
        # bind function for manage user idle time
        self.bind_all('<Any-KeyPress>', self._trig_user_idle_t)
        self.bind_all('<Any-ButtonPress>', self._trig_user_idle_t)

    def _trig_user_idle_t(self, evt=None):
        # cancel the previous event
        if self._idle_timer is not None:
            self.after_cancel(self._idle_timer)
        # create new timer
        self._idle_timer = self.after(self.user_idle_timeout, self._on_user_idle)

    def _on_user_idle(self):
        # select first tab
        self.note.select(self.tab1)


class LiveTab(Tab):
    """
    First Tab, which is the hottest from all of them
    Damn
    """

    def __init__(self, *args, **kwargs):
        Tab.__init__(self, *args, **kwargs)
        # create all tiles for this tab here
        # logo Atmo HDF
        self.tl_img_atmo = ImageRawTile(self, bg='white')
        self.tl_img_atmo.set_tile(row=0, column=0)
        # air quality Dunkerque
        self.tl_atmo_dunk = AirQualityTile(self, city='Dunkerque')
        self.tl_atmo_dunk.set_tile(row=0, column=1)
        # air quality Lille
        self.tl_atmo_lil = AirQualityTile(self, city='Lille')
        self.tl_atmo_lil.set_tile(row=0, column=2)
        # air quality Maubeuge
        self.tl_atmo_maub = AirQualityTile(self, city='Maubeuge')
        self.tl_atmo_maub.set_tile(row=0, column=3)
        # air quality Saint-Quentin
        self.tl_atmo_sque = AirQualityTile(self, city='Saint-Quentin')
        self.tl_atmo_sque.set_tile(row=0, column=4)
        # traffic map
        self.tl_tf_map = ImageRawTile(self, bg='#bbe2c6')
        self.tl_tf_map.set_tile(row=1, column=0, rowspan=3, columnspan=5)
        # weather
        self.tl_weath = WeatherTile(self)
        self.tl_weath.set_tile(row=0, column=13, rowspan=3, columnspan=4)
        # clock
        self.tl_clock = ClockTile(self)
        self.tl_clock.set_tile(row=0, column=5, rowspan=2, columnspan=3)
        # twitter cloud img
        self.tl_img_cloud = ImageRawTile(self, bg='black')
        self.tl_img_cloud.set_tile(row=2, column=5, rowspan=2, columnspan=3)
        # news banner
        self.tl_news = NewsBannerTile(self)
        self.tl_news.set_tile(row=8, column=0, columnspan=17)
        # all Gauges
        self.tl_g_veh = GaugeTile(self, title='IGP véhicule')
        self.tl_g_veh.set_tile(row=3, column=13, columnspan=2)
        self.tl_g_loc = GaugeTile(self, title='IGP locaux')
        self.tl_g_loc.set_tile(row=3, column=15, columnspan=2)
        self.tl_g_req = GaugeTile(self, title='Réunion équipe')
        self.tl_g_req.set_tile(row=4, column=13, columnspan=2)
        self.tl_g_vcs = GaugeTile(self, title='VCS')
        self.tl_g_vcs.set_tile(row=4, column=15, columnspan=2)
        self.tl_g_vst = GaugeTile(self, title='VST')
        self.tl_g_vst.set_tile(row=5, column=13, columnspan=2)
        self.tl_g_qsc = GaugeTile(self, title='1/4h sécurité')
        self.tl_g_qsc.set_tile(row=5, column=15, columnspan=2)
        # weather vigilance
        self.tl_vig_59 = VigilanceTile(self, department='Nord')
        self.tl_vig_59.set_tile(row=4, column=0)
        self.tl_vig_62 = VigilanceTile(self, department='Pas-de-Calais')
        self.tl_vig_62.set_tile(row=4, column=1)
        self.tl_vig_80 = VigilanceTile(self, department='Somme')
        self.tl_vig_80.set_tile(row=4, column=2)
        self.tl_vig_02 = VigilanceTile(self, department='Aisnes')
        self.tl_vig_02.set_tile(row=4, column=3)
        self.tl_vig_60 = VigilanceTile(self, department='Oise')
        self.tl_vig_60.set_tile(row=4, column=4)
        # Watts news
        self.tl_watts = WattsTile(self)
        self.tl_watts.set_tile(row=4, column=5, columnspan=2)
        # flyspray
        self.tl_fly = FlysprayTile(self, title='live Flyspray DTS Nord')
        self.tl_fly.set_tile(row=5, column=0, rowspan=3, columnspan=7)
        # acc days stat
        self.tl_acc = DaysAccTileLoos(self)
        self.tl_acc.set_tile(row=0, column=8, columnspan=5, rowspan=2)
        # twitter
        self.tl_tw_live = TwitterTile(self)
        self.tl_tw_live.set_tile(row=2, column=8, columnspan=5, rowspan=2)
        # grt img
        self.tl_img_grt = ImageRawTile(self, bg='white')
        self.tl_img_grt.set_tile(row=6, column=13, rowspan=2, columnspan=4)
        # carousel
        self.tl_crl = ImageRawCarouselTile(self, bg='white', raw_img_tag_d=Tags.DIR_CAROUSEL_RAW)
        self.tl_crl.set_tile(row=4, column=7, rowspan=4, columnspan=6)
        # auto-update
        self.start_cyclic_update(update_ms=5000)
        # force update at startup
        self.after(500, func=self.update)

    def update(self):
        # GRT wordcloud
        self.tl_img_cloud.raw_display = Tags.IMG_GRT_CLOUD.get()
        # traffic map
        self.tl_tf_map.raw_display = Tags.IMG_TRAFFIC_MAP.get()
        # atmo
        self.tl_img_atmo.raw_display = Tags.IMG_ATMO_HDF.get()
        # GRT
        self.tl_img_grt.raw_display = Tags.IMG_LOGO_GRT.get()
        # acc days stat
        self.tl_acc.acc_date_dts = Tags.D_GSHEET_GRT.get(('tags', 'DATE_ACC_DTS'))
        self.tl_acc.acc_date_digne = Tags.D_GSHEET_GRT.get(('tags', 'DATE_ACC_DIGNE'))
        # twitter
        self.tl_tw_live.l_tweet = Tags.D_TWEETS_GRT.get('tweets')
        # weather
        self.tl_weath.w_today_dict = Tags.D_W_TODAY_LOOS.get()
        self.tl_weath.w_forecast_dict = Tags.D_W_FORECAST_LOOS.get()
        # air Dunkerque
        self.tl_atmo_dunk.qlt_index = Tags.D_ATMO_QUALITY.get('dunkerque')
        # air Lille
        self.tl_atmo_lil.qlt_index = Tags.D_ATMO_QUALITY.get('lille')
        # air Maubeuge
        self.tl_atmo_maub.qlt_index = Tags.D_ATMO_QUALITY.get('maubeuge')
        # air Saint-Quentin
        self.tl_atmo_sque.qlt_index = Tags.D_ATMO_QUALITY.get('saint-quentin')
        # update news widget
        self.tl_news.l_titles = Tags.D_NEWS_LOCAL.get()
        # gauges update
        self.tl_g_veh.percent = Tags.D_GSHEET_GRT.get(('tags', 'IGP_VEH_JAUGE_DTS'))
        self.tl_g_veh.header_str = '%s/%s' % (Tags.D_GSHEET_GRT.get(('tags', 'IGP_VEH_REAL_DTS')),
                                              Tags.D_GSHEET_GRT.get(('tags', 'IGP_VEH_OBJ_DTS')))
        self.tl_g_loc.percent = Tags.D_GSHEET_GRT.get(('tags', 'IGP_LOC_JAUGE_DTS'))
        self.tl_g_loc.header_str = '%s/%s' % (Tags.D_GSHEET_GRT.get(('tags', 'IGP_LOC_REAL_DTS')),
                                              Tags.D_GSHEET_GRT.get(('tags', 'IGP_LOC_OBJ_DTS')))
        self.tl_g_req.percent = Tags.D_GSHEET_GRT.get(('tags', 'R_EQU_JAUGE_DTS'))
        self.tl_g_req.header_str = '%s/%s' % (Tags.D_GSHEET_GRT.get(('tags', 'R_EQU_REAL_DTS')),
                                              Tags.D_GSHEET_GRT.get(('tags', 'R_EQU_OBJ_DTS')))
        self.tl_g_vcs.percent = Tags.D_GSHEET_GRT.get(('tags', 'VCS_JAUGE_DTS'))
        self.tl_g_vcs.header_str = '%s/%s' % (Tags.D_GSHEET_GRT.get(('tags', 'VCS_REAL_DTS')),
                                              Tags.D_GSHEET_GRT.get(('tags', 'VCS_OBJ_DTS')))
        self.tl_g_vst.percent = Tags.D_GSHEET_GRT.get(('tags', 'VST_JAUGE_DTS'))
        self.tl_g_vst.header_str = '%s/%s' % (Tags.D_GSHEET_GRT.get(('tags', 'VST_REAL_DTS')),
                                              Tags.D_GSHEET_GRT.get(('tags', 'VST_OBJ_DTS')))
        self.tl_g_qsc.percent = Tags.D_GSHEET_GRT.get(('tags', 'Q_HRE_JAUGE_DTS'))
        self.tl_g_qsc.header_str = '%s/%s' % (Tags.D_GSHEET_GRT.get(('tags', 'Q_HRE_REAL_DTS')),
                                              Tags.D_GSHEET_GRT.get(('tags', 'Q_HRE_OBJ_DTS')))
        # weather vigilance
        self.tl_vig_59.vig_level = Tags.D_WEATHER_VIG.get(('department', '59', 'vig_level'))
        self.tl_vig_59.risk_ids = Tags.D_WEATHER_VIG.get(('department', '59', 'risk_id'))
        self.tl_vig_62.vig_level = Tags.D_WEATHER_VIG.get(('department', '62', 'vig_level'))
        self.tl_vig_62.risk_ids = Tags.D_WEATHER_VIG.get(('department', '62', 'risk_id'))
        self.tl_vig_80.vig_level = Tags.D_WEATHER_VIG.get(('department', '80', 'vig_level'))
        self.tl_vig_80.risk_ids = Tags.D_WEATHER_VIG.get(('department', '80', 'risk_id'))
        self.tl_vig_02.vig_level = Tags.D_WEATHER_VIG.get(('department', '02', 'vig_level'))
        self.tl_vig_02.risk_ids = Tags.D_WEATHER_VIG.get(('department', '02', 'risk_id'))
        self.tl_vig_60.vig_level = Tags.D_WEATHER_VIG.get(('department', '60', 'vig_level'))
        self.tl_vig_60.risk_ids = Tags.D_WEATHER_VIG.get(('department', '60', 'risk_id'))
        # Watts news
        self.tl_watts.pwr = Tags.MET_PWR_ACT.get()
        self.tl_watts.today_wh = Tags.MET_TODAY_WH.get()
        self.tl_watts.yesterday_wh = Tags.MET_YESTERDAY_WH.get()
        # flyspray
        self.tl_fly.l_items = Tags.L_FLYSPRAY_RSS.get()


# main
if __name__ == '__main__':
    # logging setup
    logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)
    logging.info('board-hmi-app started')
    # init Tags
    Tags.init()
    # start tkinter
    app = MainApp()
    app.title('GRTgaz Dashboard')
    app.attributes('-fullscreen', True)
    app.mainloop()

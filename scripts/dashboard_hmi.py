#!/usr/bin/env python3

try:
    # Python 2.x
    import Tkinter as tk
    import ttk
except ImportError:
    # Python 3.x
    import tkinter as tk
    from tkinter import ttk

from configparser import ConfigParser
import json
import locale
import logging
import traceback
import redis
import time
from datetime import datetime, timedelta
import threading
import glob
import os
import subprocess
import math

"""
Author : LECORNET Didrick
Date : 02/05/2018
Project : GRTgaz interractif and dynamic supervisor dashboard
Step : file independant, can be used without pdf and images
"""

# some const
IMG_PATH = "/home/pi/dashboard/images/"
PDF_PATH = "/home/pi/dashboard/pdf_reglementation/"
DOC_PATH = "/home/pi/dashboard/Document_affichage/"
# Geometry
TAB_PAD_HEIGHT = 17
TAB_PAD_WIDTH = 17
NEWS_BANNER_HEIGHT = 90
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
# hostname of master dashboard
dash_master_host = cnf.get("dashboard", "master_host")
# hostname of bridge server
bridge_host = cnf.get("bridge", "bridge_host")
# gmap img traffic
gmap_img_target = cnf.get("gmap_img", "img_target")
# twitter cloud img
tw_cloud_img = cnf.get("twitter", "cloud_img")


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


class DB:
    # create connector
    master = CustomRedis(host=dash_master_host, socket_timeout=4, socket_keepalive=True)
    bridge = CustomRedis(host=bridge_host, socket_timeout=4, socket_keepalive=True)


class Tag:
    all_tags = []

    def __init__(self, init=None, cmd_src=None):
        # private
        self._var_lock = threading.Lock()
        self._var = init
        self._subscribers = []
        self._cmd_src = cmd_src
        # record the tag in tags list
        Tag.all_tags.append(self)

    def __repr__(self):
        return repr(self._var)

    def update(self):
        if self._cmd_src:
            self.var = self._cmd_src()

    @property
    def var(self):
        with self._var_lock:
            return self._var

    @var.setter
    def var(self, value):
        with self._var_lock:
            if value != self._var:
                self._var = value
                for callback in self._subscribers:
                    callback(self._var)

    def subscribe(self, callback):
        # first value
        callback(self._var)
        # subscribe
        self._subscribers.append(callback)

    @classmethod
    def update_all(cls):
        for tag in cls.all_tags:
            tag.update()

    def get(self, path=None):
        if path:
            if not type(path) in (tuple, list):
                path = [path]
            try:
                data = self._var
                for i in range(0, len(path)):
                    data = data[path[i]]
                return data
            except:
                return None
        else:
            return self._var

    def set(self, *args):
        self._var.set(*args)


class Tags:
    # create all tag here
    # WARNs: -> all tag are manage by an IO thread
    #        -> tag subscriber callback code are call by IO thread (not by tkinter main thread)
    D_GSHEET_GRT = Tag(cmd_src=lambda: DB.master.get_obj("gsheet:grt"))
    D_ISWIP_ROOM = Tag(cmd_src=lambda: DB.master.get_obj("iswip:room_status"))
    D_ATMO_QUALITY = Tag(cmd_src=lambda: DB.master.get_obj("atmo:quality"))
    D_W_TODAY_LOOS = Tag(cmd_src=lambda: DB.master.get_obj("weather:today:loos"))
    D_W_FORECAST_LOOS = Tag(cmd_src=lambda: DB.master.get_obj("weather:forecast:loos"))
    D_WEATHER_VIG = Tag(cmd_src=lambda: DB.master.get_obj("weather:vigilance"))
    D_NEWS_LOCAL = Tag(cmd_src=lambda: DB.master.get_obj("news:local"))
    D_TWEETS_GRT = Tag(cmd_src=lambda: DB.master.get_obj("twitter:tweets:grtgaz"))
    MET_PWR_ACT = Tag(cmd_src=lambda: DB.master.get_obj("meters:electric:site:pwr_act"))
    MET_TODAY_WH = Tag(cmd_src=lambda: DB.master.get_obj("meters:electric:site:today_wh"))
    MET_YESTERDAY_WH = Tag(cmd_src=lambda: DB.master.get_obj("meters:electric:site:yesterday_wh"))
    L_FLYSPRAY_RSS = Tag(cmd_src=lambda: DB.bridge.get_obj("rx:bur:flyspray_rss"))

    @classmethod
    def tags_io_thread(cls):
        # for tag auto-update method (with cmd_srv)
        while True:
            Tag.update_all()
            time.sleep(2.0)


class MainApp(tk.Tk):
    def __init__(self, *args, **kwargs):
        tk.Tk.__init__(self, *args, **kwargs)
        # public
        self.user_idle_timeout = 120000
        # private
        self._idle_timer = None
        # tk stuff
        # remove mouse icon for a dashboard
        self.config(cursor="none")
        # define style to fix size of tab header
        self.style = ttk.Style()
        self.style.theme_settings("default",
                                  {"TNotebook.Tab": {"configure": {"padding": [TAB_PAD_WIDTH, TAB_PAD_HEIGHT]}}})
        # define notebook
        self.note = ttk.Notebook(self)
        self.tab1 = LiveTab(self.note)
        self.tab2 = PdfTab(self.note, pdf_path=PDF_PATH)
        self.note.add(self.tab1, text="Tableau de bord")
        self.note.add(self.tab2, text="Affichage réglementaire")
        self.note.pack()
        # default tab
        self.note.select(self.tab1)
        # press Esc to quit
        self.bind("<Escape>", lambda e: self.destroy())
        # bind function keys to tabs
        self.bind("<F1>", lambda evt: self.note.select(self.tab1))
        self.bind("<F2>", lambda evt: self.note.select(self.tab2))
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


class Tab(tk.Frame):
    """
    Base Tab class, with a frame full of tile, can be derived as you need it
    """

    def __init__(self, *args, **kwargs):
        tk.Frame.__init__(self, *args, **kwargs)
        # public
        self._update_ms = None
        self.nb_tile_w = 17
        self.nb_tile_h = 9
        # private
        self._screen_w = self.winfo_screenwidth()
        self._screen_h = self.winfo_screenheight() - 60
        self._lbl__padx = round(self._screen_w / (self.nb_tile_w * 2))
        self._lbl_pady = round((self._screen_h - TAB_PAD_HEIGHT) / (self.nb_tile_h * 2))
        # tk stuff
        # populate the grid with all tiles
        for c in range(0, self.nb_tile_w):
            for r in range(0, self.nb_tile_h):
                self.grid_rowconfigure(r, weight=1)
                # create Labels to space all of it
                tk.Label(self, pady=self._lbl_pady, padx=self._lbl__padx).grid(column=c, row=r)
                Tile(self).set_tile(row=r, column=c)
            self.grid_columnconfigure(c, weight=1)
        # init tab update
        self.bind('<Visibility>', lambda evt: self.update())

    def start_cyclic_update(self, update_ms=500):
        self._update_ms = update_ms
        # init loop
        self._do_cyclic_update()

    def _do_cyclic_update(self):
        if self.winfo_ismapped():
            self.update()
        self.after(self._update_ms, self._do_cyclic_update)

    def update(self):
        pass


class LiveTab(Tab):
    """
    First Tab, which is the hottest from all of them
    Damn
    """

    def __init__(self, *args, **kwargs):
        Tab.__init__(self, *args, **kwargs)
        # create all tiles for this tab here
        # logo Atmo HDF
        self.tl_img_atmo = ImageTile(self, file=IMG_PATH + "logo_atmo_hdf.png", bg="white")
        self.tl_img_atmo.set_tile(row=0, column=0)
        # air quality Dunkerque
        self.tl_atmo_dunk = AirQualityTile(self, city="Dunkerque")
        self.tl_atmo_dunk.set_tile(row=0, column=1)
        # air quality Lille
        self.tl_atmo_lil = AirQualityTile(self, city="Lille")
        self.tl_atmo_lil.set_tile(row=0, column=2)
        # air quality Maubeuge
        self.tl_atmo_maub = AirQualityTile(self, city="Maubeuge")
        self.tl_atmo_maub.set_tile(row=0, column=3)
        # air quality Saint-Quentin
        self.tl_atmo_sque = AirQualityTile(self, city="Saint-Quentin")
        self.tl_atmo_sque.set_tile(row=0, column=4)
        # traffic map
        self.tl_tf_map = ImageRefreshTile(self, file=gmap_img_target, img_ratio=2, bg="white")
        self.tl_tf_map.set_tile(row=1, column=0, rowspan=3, columnspan=5)
        # weather
        self.tl_weath = WeatherTile(self)
        self.tl_weath.set_tile(row=0, column=13, rowspan=3, columnspan=4)
        # clock
        self.tl_clock = ClockTile(self)
        self.tl_clock.set_tile(row=0, column=5, rowspan=2, columnspan=3)
        # twitter cloud img
        self.tl_img_cloud = ImageRefreshTile(self, file=tw_cloud_img, bg='black')
        self.tl_img_cloud.set_tile(row=2, column=5, rowspan=2, columnspan=3)
        # news banner
        self.tl_news = NewsBannerTile(self)
        self.tl_news.set_tile(row=8, column=0, columnspan=17)
        # all Gauges
        self.tl_g_veh = GaugeTile(self, title="IGP véhicule")
        self.tl_g_veh.set_tile(row=3, column=13, columnspan=2)
        self.tl_g_loc = GaugeTile(self, title="IGP locaux")
        self.tl_g_loc.set_tile(row=3, column=15, columnspan=2)
        self.tl_g_req = GaugeTile(self, title="Réunion équipe")
        self.tl_g_req.set_tile(row=4, column=13, columnspan=2)
        self.tl_g_vcs = GaugeTile(self, title="VCS")
        self.tl_g_vcs.set_tile(row=4, column=15, columnspan=2)
        self.tl_g_vst = GaugeTile(self, title="VST")
        self.tl_g_vst.set_tile(row=5, column=13, columnspan=2)
        self.tl_g_qsc = GaugeTile(self, title="1/4h sécurité")
        self.tl_g_qsc.set_tile(row=5, column=15, columnspan=2)
        # weather vigilance
        self.tl_vig_59 = VigilanceTile(self, department="Nord")
        self.tl_vig_59.set_tile(row=4, column=0)
        self.tl_vig_62 = VigilanceTile(self, department="Pas-de-Calais")
        self.tl_vig_62.set_tile(row=4, column=1)
        self.tl_vig_80 = VigilanceTile(self, department="Somme")
        self.tl_vig_80.set_tile(row=4, column=2)
        self.tl_vig_02 = VigilanceTile(self, department="Aisnes")
        self.tl_vig_02.set_tile(row=4, column=3)
        self.tl_vig_60 = VigilanceTile(self, department="Oise")
        self.tl_vig_60.set_tile(row=4, column=4)
        # Watts news
        self.tl_watts = WattsTile(self)
        self.tl_watts.set_tile(row=4, column=5, columnspan=2)
        # flyspray
        self.tl_fly = FlysprayTile(self)
        self.tl_fly.set_tile(row=5, column=0,  rowspan=3, columnspan=5)
        # meeting room
        self.tl_room_prj = MeetingRoomTile(self, room="Salle project")
        self.tl_room_prj.set_tile(row=5, column=5,columnspan=2)
        self.tl_room_trn = MeetingRoomTile(self, room="Salle trainning")
        self.tl_room_trn.set_tile(row=6, column=5, columnspan=2)
        self.tl_room_met = MeetingRoomTile(self, room="Salle meeting")
        self.tl_room_met.set_tile(row=7, column=5, columnspan=2)
        # self.tl_room_bur1 = MeetingRoomTile(self, room="Bureau passage 1")
        # self.tl_room_bur1.set_tile(row=5, column=2, columnspan=2)
        # self.tl_room_bur2 = MeetingRoomTile(self, room="Bureau passage 2")
        # self.tl_room_bur2.set_tile(row=6, column=2, columnspan=2)
        # acc days stat
        self.tl_acc = DaysAccTile(self)
        self.tl_acc.set_tile(row=0, column=8, columnspan=5, rowspan=2)
        # twitter
        self.tl_tw_live = TwitterTile(self)
        self.tl_tw_live.set_tile(row=2, column=8, columnspan=5, rowspan=2)
        # logo img
        self.tl_img_logo = ImageTile(self, file=IMG_PATH + "logo.png", bg="white")
        self.tl_img_logo.set_tile(row=6, column=13, rowspan=2, columnspan=4)
        # carousel
        self.tl_crl = ImageCarouselTile(self)
        self.tl_crl.set_tile(row=4, column=7, rowspan=4, columnspan=6)
        # auto-update clock
        self.start_cyclic_update(update_ms=5000)

    def update(self):
        # acc days stat
        self.tl_acc.acc_date_dts = Tags.D_GSHEET_GRT.get(("tags", "DATE_ACC_DTS"))
        self.tl_acc.acc_date_digne = Tags.D_GSHEET_GRT.get(("tags", "DATE_ACC_DIGNE"))
        # twitter
        self.tl_tw_live.l_tweet = Tags.D_TWEETS_GRT.get("tweets")
        # weather
        self.tl_weath.w_today_dict = Tags.D_W_TODAY_LOOS.get()
        self.tl_weath.w_forecast_dict = Tags.D_W_FORECAST_LOOS.get()
        # air Dunkerque
        self.tl_atmo_dunk.qlt_index = Tags.D_ATMO_QUALITY.get("dunkerque")
        # air Lille
        self.tl_atmo_lil.qlt_index = Tags.D_ATMO_QUALITY.get("lille")
        # air Maubeuge
        self.tl_atmo_maub.qlt_index = Tags.D_ATMO_QUALITY.get("maubeuge")
        # air Saint-Quentin
        self.tl_atmo_sque.qlt_index = Tags.D_ATMO_QUALITY.get("saint-quentin")
        # update news widget
        self.tl_news.l_titles = Tags.D_NEWS_LOCAL.get()
        # gauges update
        self.tl_g_veh.percent = Tags.D_GSHEET_GRT.get(("tags", "IGP_VEH_JAUGE_DTS"))
        self.tl_g_veh.header_str = "%s/%s" % (Tags.D_GSHEET_GRT.get(("tags", "IGP_VEH_REAL_DTS")),
                                              Tags.D_GSHEET_GRT.get(("tags", "IGP_VEH_OBJ_DTS")))
        self.tl_g_loc.percent = Tags.D_GSHEET_GRT.get(("tags", "IGP_LOC_JAUGE_DTS"))
        self.tl_g_loc.header_str = "%s/%s" % (Tags.D_GSHEET_GRT.get(("tags", "IGP_LOC_REAL_DTS")),
                                              Tags.D_GSHEET_GRT.get(("tags", "IGP_LOC_OBJ_DTS")))
        self.tl_g_req.percent = Tags.D_GSHEET_GRT.get(("tags", "R_EQU_JAUGE_DTS"))
        self.tl_g_req.header_str = "%s/%s" % (Tags.D_GSHEET_GRT.get(("tags", "R_EQU_REAL_DTS")),
                                              Tags.D_GSHEET_GRT.get(("tags", "R_EQU_OBJ_DTS")))
        self.tl_g_vcs.percent = Tags.D_GSHEET_GRT.get(("tags", "VCS_JAUGE_DTS"))
        self.tl_g_vcs.header_str = "%s/%s" % (Tags.D_GSHEET_GRT.get(("tags", "VCS_REAL_DTS")),
                                              Tags.D_GSHEET_GRT.get(("tags", "VCS_OBJ_DTS")))
        self.tl_g_vst.percent = Tags.D_GSHEET_GRT.get(("tags", "VST_JAUGE_DTS"))
        self.tl_g_vst.header_str = "%s/%s" % (Tags.D_GSHEET_GRT.get(("tags", "VST_REAL_DTS")),
                                              Tags.D_GSHEET_GRT.get(("tags", "VST_OBJ_DTS")))
        self.tl_g_qsc.percent = Tags.D_GSHEET_GRT.get(("tags", "Q_HRE_JAUGE_DTS"))
        self.tl_g_qsc.header_str = "%s/%s" % (Tags.D_GSHEET_GRT.get(("tags", "Q_HRE_REAL_DTS")),
                                              Tags.D_GSHEET_GRT.get(("tags", "Q_HRE_OBJ_DTS")))
        # weather vigilance
        self.tl_vig_59.vig_level = Tags.D_WEATHER_VIG.get(("department", "59", "vig_level"))
        self.tl_vig_59.risk_ids = Tags.D_WEATHER_VIG.get(("department", "59", "risk_id"))
        self.tl_vig_62.vig_level = Tags.D_WEATHER_VIG.get(("department", "62", "vig_level"))
        self.tl_vig_62.risk_ids = Tags.D_WEATHER_VIG.get(("department", "62", "risk_id"))
        self.tl_vig_80.vig_level = Tags.D_WEATHER_VIG.get(("department", "80", "vig_level"))
        self.tl_vig_80.risk_ids = Tags.D_WEATHER_VIG.get(("department", "80", "risk_id"))
        self.tl_vig_02.vig_level = Tags.D_WEATHER_VIG.get(("department", "02", "vig_level"))
        self.tl_vig_02.risk_ids = Tags.D_WEATHER_VIG.get(("department", "02", "risk_id"))
        self.tl_vig_60.vig_level = Tags.D_WEATHER_VIG.get(("department", "60", "vig_level"))
        self.tl_vig_60.risk_ids = Tags.D_WEATHER_VIG.get(("department", "60", "risk_id"))
        # Watts news
        self.tl_watts.pwr = Tags.MET_PWR_ACT.get()
        self.tl_watts.today_wh = Tags.MET_TODAY_WH.get()
        self.tl_watts.yesterday_wh = Tags.MET_YESTERDAY_WH.get()
        # update room status
        self.tl_room_trn.status = Tags.D_ISWIP_ROOM.get("Salle_TRAINNING")
        self.tl_room_prj.status = Tags.D_ISWIP_ROOM.get("Salle_PROJECT")
        self.tl_room_met.status = Tags.D_ISWIP_ROOM.get("Salle_MEETING")
        # self.tl_room_bur1.status = Tags.D_ISWIP_ROOM.get("Bureau_Passage_1")
        # self.tl_room_bur2.status = Tags.D_ISWIP_ROOM.get("Bureau_Passage_2")
        # flyspray
        self.tl_fly.l_items = Tags.L_FLYSPRAY_RSS.get()


class PdfTab(Tab):
    def __init__(self, *args, pdf_path="", **kwargs):
        Tab.__init__(self, *args, **kwargs)
        # public
        self.pdf_path = pdf_path
        # private
        self._l_tl_pdf = list()
        # tk stuff
        # bind update in visibility event
        self.bind('<Visibility>', lambda evt: self.update())

    # populate (or redo it) the tab with all PdfOpenerTile
    def update(self):
        try:
            # list all PDF
            pdf_file_l = glob.glob(self.pdf_path + "*.pdf")
            pdf_file_l.sort()
            # if there is any difference in the pdf list, REFRESH, else don't, there is no need
            if pdf_file_l != [pdf_tl.file for pdf_tl in self._l_tl_pdf]:
                # remove all old tiles
                for tl_pdf in self._l_tl_pdf:
                    tl_pdf.destroy()
                self._l_tl_pdf = list()
                # populate with new tiles
                # start at 1:1 pos
                (r, c) = (1, 1)
                for pdf_file in pdf_file_l:
                    self._l_tl_pdf.append(PdfOpenerTile(self, file=pdf_file))
                    self._l_tl_pdf[-1].set_tile(row=r, column=c, columnspan=5, rowspan=1)
                    c += 5
                    if c >= self.nb_tile_w - 1:
                        r += 1
                        c = 1
        except Exception:
            logging.error(traceback.format_exc())


class Tile(tk.Frame):
    """
    Source of all the tile here
    Default : a gray, black bordered, case
    """

    def __init__(self, *args, **kwargs):
        tk.Frame.__init__(self, *args, **kwargs)
        # public
        # private
        self._update_ms = None
        # tk stuff
        self.configure(highlightbackground=ARDOISE)
        self.configure(highlightthickness=3)
        self.configure(bd=0)
        # set background, if current bg is tk default one
        if self.cget("bg") == "#d9d9d9":
            self.configure(bg=VERT)
        # deny frame resize
        self.pack_propagate(False)
        self.grid_propagate(False)

    def set_tile(self, row=0, column=0, rowspan=1, columnspan=1):
        # function to print a tile on the screen at the given coordonates
        self.grid(row=row, column=column, rowspan=rowspan, columnspan=columnspan, sticky=tk.NSEW)

    # def del_tile(self):
    #     self.grid_remove()

    def start_cyclic_update(self, update_ms=500):
        self._update_ms = update_ms
        # first update
        self.update()
        # init loop
        self._do_cyclic_update()

    def _do_cyclic_update(self):
        if self.winfo_ismapped():
            self.update()
        self.after(self._update_ms, self._do_cyclic_update)

    def update(self):
        pass


class TwitterTile(Tile):
    TW_BLUE = "#1dcaff"

    def __init__(self, *args, **kwargs):
        Tile.__init__(self, *args, **kwargs)
        # public
        # private
        self._l_tweet = None
        self._tw_text = tk.StringVar()
        self._tw_text.set("n/a")
        self._tw_index = 0
        # tk job
        self.configure(bg=TwitterTile.TW_BLUE)
        tk.Label(self, text="live twitter: GRTgaz", bg=self.cget("bg"),
                 font=("courier", 14, "bold", "underline")).pack()
        tk.Label(self, textvariable=self._tw_text, bg=self.cget("bg"),
                 wraplength=550, font=("courier", 14, "bold")).pack(expand=True)
        # auto-update carousel rotate
        self.start_cyclic_update(update_ms=12000)

    @property
    def l_tweet(self):
        return self._l_tweet

    @l_tweet.setter
    def l_tweet(self, value):
        # check type
        try:
            value = list(value)
        except (TypeError, ValueError):
            value = None
        # check change
        if self._l_tweet != value:
            self._l_tweet = value
            # priority fart last tweet
            self._tw_index = 0
            self.update()

    def update(self):
        if self.l_tweet:
            if self._tw_index >= len(self._l_tweet):
                self._tw_index = 0
            self._tw_text.set(self._l_tweet[self._tw_index])
            self._tw_index += 1
        else:
            self._tw_index = 0
            self._tw_text.set("n/a")


class FlysprayTile(Tile):
    def __init__(self, *args, **kwargs):
        Tile.__init__(self, *args, **kwargs)
        # public
        # private
        self._l_items = None
        self._msg_text = tk.StringVar()
        self._msg_text.set("n/a")
        # tk job
        tk.Label(self, text="live Flyspray DTS Nord", bg=self.cget("bg"),
                 font=("courier", 14, "bold", "underline")).pack()
        tk.Label(self, textvariable=self._msg_text, bg=self.cget("bg"),
                 wraplength=550, justify=tk.LEFT, font=("courier", 11)).pack(expand=True)

    @property
    def l_items(self):
        return self._l_items

    @l_items.setter
    def l_items(self, value):
        # check type
        try:
            value = list(value)
        except (TypeError, ValueError):
            value = None
        # check change
        if self._l_items != value:
            self._l_items = value
            self._on_data_change()

    def _on_data_change(self):
        try:
            msg = ""
            for item in self._l_items[:12]:
                msg += "%s\n" % item['title']
            self._msg_text.set(msg)
        except Exception:
            self._msg_text.set("n/a")

# deprecated
# class TrafficDurationTile(Tile):
#     def __init__(self, *args, to_city, **kwargs):
#         Tile.__init__(self, *args, **kwargs)
#         # public
#         self.to_city = to_city
#         # private
#         self._travel_t = 0
#         self._traffic_t = 0
#         self._traffic_str = tk.StringVar()
#         self._t_inc_str = tk.StringVar()
#         self._traffic_str.set("N/A")
#         self._t_inc_str.set("N/A")
#         # tk job
#         tk.Label(self, text=to_city, font="bold").pack()
#         tk.Label(self).pack()
#         tk.Label(self, textvariable=self._traffic_str).pack()
#         tk.Label(self, textvariable=self._t_inc_str).pack()
#
#     @property
#     def travel_t(self):
#         return self._travel_t
#
#     @travel_t.setter
#     def travel_t(self, value):
#         # check type
#         try:
#             value = int(value)
#         except (TypeError, ValueError):
#             value = None
#         # check change
#         if self._travel_t != value:
#             self._travel_t = value
#             self._on_data_change()
#
#     @property
#     def traffic_t(self):
#         return self._travel_t
#
#     @traffic_t.setter
#     def traffic_t(self, value):
#         # check type
#         try:
#             value = int(value)
#         except (TypeError, ValueError):
#             value = None
#         # check change
#         if self._traffic_t != value:
#             self._traffic_t = value
#             self._on_data_change()
#
#     def _on_data_change(self):
#         try:
#             t_increase = self._traffic_t - self._travel_t
#             t_increase_ratio = t_increase / self._travel_t
#         except (TypeError, ZeroDivisionError):
#             # set tk var
#             self._traffic_str.set("N/A")
#             self._t_inc_str.set("N/A")
#             # choose tile color
#             tile_color = "pink"
#         else:
#             # set tk var
#             self._traffic_str.set("%.0f mn" % (self._traffic_t / 60))
#             self._t_inc_str.set("%+.0f mn" % (t_increase / 60))
#             # choose tile color
#             tile_color = "green"
#             if t_increase_ratio > 0.50:
#                 tile_color = "red"
#             elif t_increase_ratio > 0.15:
#                 tile_color = "orange"
#         # update tile and his childs color
#         for w in self.winfo_children():
#             w.configure(bg=tile_color)
#         self.configure(bg=tile_color)


class AirQualityTile(Tile):
    QUALITY_LVL = ("n/a", "très bon", "très bon", "bon", "bon", "moyen",
                   "médiocre", "médiocre", "mauvais", "mauvais", "très mauvais")

    def __init__(self, *args, city, **kwargs):
        Tile.__init__(self, *args, **kwargs)
        # public
        self.city = city
        # private
        self._qlt_index = 0
        self._index_str = tk.StringVar()
        self._status_str = tk.StringVar()
        self._index_str.set("N/A")
        self._status_str.set("N/A")
        # tk job
        tk.Label(self, text=city, font="bold").pack()
        tk.Label(self).pack()
        tk.Label(self, textvariable=self._index_str).pack()
        tk.Label(self, textvariable=self._status_str).pack()

    @property
    def qlt_index(self):
        return self._qlt_index

    @qlt_index.setter
    def qlt_index(self, value):
        # check type
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = None
        # check change
        if self._qlt_index != value:
            self._qlt_index = value
            self._on_data_change()

    def _on_data_change(self):
        try:
            self._index_str.set("%d/10" % self._qlt_index)
            self._status_str.set(AirQualityTile.QUALITY_LVL[self._qlt_index])
        except (TypeError, ZeroDivisionError):
            # set tk var
            self._index_str.set("N/A")
            self._status_str.set("N/A")
            # choose tile color
            tile_color = "pink"
        else:
            # choose tile color
            tile_color = "green"
            if self._qlt_index > 7:
                tile_color = "firebrick"
            elif self._qlt_index > 4:
                tile_color = "orange"
        # update tile and his childs color
        for w in self.winfo_children():
            w.configure(bg=tile_color)
        self.configure(bg=tile_color)


class VigilanceTile(Tile):
    VIG_LVL = ["verte", "jaune", "orange", "rouge"]
    VIG_COLOR = ["green", "yellow", "orange", "firebrick"]
    ID_RISK = ["n/a", "vent", "pluie", "orages", "inondation", "neige verglas",
               "canicule", "grand froid", "avalanches", "submersion"]

    def __init__(self, *args, department="", **kwargs):
        Tile.__init__(self, *args, **kwargs)
        # public
        self.department = department
        # private
        self._vig_level = None
        self._risk_ids = []
        self._level_str = tk.StringVar()
        self._risk_str = tk.StringVar()
        self._level_str.set("N/A")
        self._risk_str.set("")
        # tk job
        self.configure(bg="pink")
        tk.Label(self, text="Vigilance", font="bold", bg="pink").pack()
        tk.Label(self, text=self.department, font="bold", bg="pink").pack()
        tk.Label(self, font=("", 6), bg="pink").pack()
        tk.Label(self, textvariable=self._level_str, font="bold", bg="pink").pack()
        tk.Label(self, textvariable=self._risk_str, font=("", 8), bg="pink").pack()

    @property
    def vig_level(self):
        return self._vig_level

    @vig_level.setter
    def vig_level(self, value):
        # check type
        try:
            value = int(value) - 1
        except (TypeError, ValueError):
            value = None
        # check change
        if self._vig_level != value:
            self._vig_level = value
            self._on_data_change()

    @property
    def risk_ids(self):
        return self._risk_ids

    @risk_ids.setter
    def risk_ids(self, value):
        # check type
        try:
            value = [int(i) for i in list(value)]
        except (TypeError, ValueError):
            value = []
        # check change
        if self._risk_ids != value:
            self._risk_ids = value
            self._on_data_change()

    def _on_data_change(self):
        try:
            self._level_str.set("%s" % VigilanceTile.VIG_LVL[self._vig_level].upper())
            tile_color = VigilanceTile.VIG_COLOR[self._vig_level]
        except (IndexError, TypeError):
            # set tk var
            self._level_str.set("N/A")
            # choose tile color
            tile_color = "pink"
        try:
            str_risk = " "
            for id_risk in self._risk_ids[:2]:
                str_risk += VigilanceTile.ID_RISK[id_risk] + " "
            self._risk_str.set("%s" % str_risk)
        except (IndexError, TypeError):
            # set tk var
            self._risk_str.set("n/a")
        # update tile and his childs color
        for w in self.winfo_children():
            w.configure(bg=tile_color)
        self.configure(bg=tile_color)


class WattsTile(Tile):
    def __init__(self, *args, **kwargs):
        Tile.__init__(self, *args, **kwargs)
        # public
        # private
        self._pwr = None
        self._tdy_wh = None
        self._ydy_wh = None
        self._pwr_text = tk.StringVar()
        self._tdy_text = tk.StringVar()
        self._ydy_text = tk.StringVar()
        # tk job
        tk.Label(self, text="Loos Watts news", bg=self.cget("bg"), font=("courier", 14, "bold", "underline")).pack()
        tk.Label(self, textvariable=self._pwr_text, bg=self.cget("bg"), font=("courier", 14, "bold")).pack(expand=True)
        tk.Label(self, textvariable=self._tdy_text, bg=self.cget("bg"), font=("courier", 14, "bold")).pack(expand=True)
        tk.Label(self, textvariable=self._ydy_text, bg=self.cget("bg"), font=("courier", 14, "bold")).pack(expand=True)
        # public with accessor
        self.pwr = None
        self.today_wh = None
        self.yesterday_wh = None

    @property
    def pwr(self):
        return self._pwr

    @pwr.setter
    def pwr(self, value):
        # check type
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = None
        # check change
        if self._pwr != value:
            self._pwr = value
        # update tk lbl
        self._pwr_text.set("  P %5s w  " % ("n/a" if self._pwr is None else self._pwr))

    @property
    def today_wh(self):
        return self._tdy_wh

    @today_wh.setter
    def today_wh(self, value):
        # check type
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = None
        # check change
        if self._tdy_wh != value:
            self._tdy_wh = value
        # update tk lbl
        self._tdy_text.set("  J %5s kwh" % ("n/a" if self._tdy_wh is None else round(self._tdy_wh / 1000)))

    @property
    def yesterday_wh(self):
        return self._ydy_wh

    @yesterday_wh.setter
    def yesterday_wh(self, value):
        # check type
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = None
        # check change
        if self._ydy_wh != value:
            self._ydy_wh = value
        # update tk lbl
        self._ydy_text.set("J-1 %5s kwh" % ("n/a" if self._ydy_wh is None else round(self._ydy_wh / 1000)))


class WeatherTile(Tile):  # principal, she own all the day, could be divided if wanted #json
    def __init__(self, *args, **kwargs):
        Tile.__init__(self, *args, **kwargs)
        # public
        # private
        self._w_today_dict = None
        self._w_forecast_dict = None
        self._days_f_l = list()
        self._days_lbl = list()
        # tk stuff
        # build 4x3 grid
        for c in range(4):
            for r in range(3):
                self.grid_rowconfigure(r, weight=1)
                tk.Label(master=self, pady=0, padx=0).grid(column=c, row=r)
            self.grid_columnconfigure(c, weight=1)
            # creation
            self._days_f_l.append(
                tk.LabelFrame(master=self, text="dd/mm/yyyy", bg=self.cget("bg"),
                              font=("bold", 10)))
            self._days_lbl.append(
                tk.Label(master=self._days_f_l[c], text="n/a", bg=self.cget("bg"),
                         font='bold', anchor=tk.W, justify=tk.LEFT))
            # end creation
            # impression
            self._days_f_l[c].grid(row=2, column=c, sticky=tk.NSEW)
            self._days_f_l[c].grid_propagate(False)
            self._days_lbl[c].grid(sticky=tk.NSEW)
            self._days_lbl[c].grid_propagate(False)

        # today frame
        self.frm_today = tk.LabelFrame(master=self, bg=self.cget("bg"), text="n/a", font=("bold", 18))
        self.lbl_today = tk.Label(master=self.frm_today, text="n/a", bg=self.cget("bg"), font=('courier', 18, 'bold'),
                                  anchor=tk.W, justify=tk.LEFT)
        self.frm_today.grid(row=0, column=0, columnspan=4, rowspan=2, sticky=tk.NSEW)
        self.frm_today.grid_propagate(False)
        self.lbl_today.grid(column=0)
        self.lbl_today.grid_propagate(False)

    @property
    def w_today_dict(self):
        return self._w_today_dict

    @w_today_dict.setter
    def w_today_dict(self, value):
        # check type
        try:
            value = dict(value)
        except (TypeError, ValueError):
            value = None
        # check change
        if self._w_today_dict != value:
            self._w_today_dict = value
            self._on_today_change()

    @property
    def w_forecast_dict(self):
        return self._w_forecast_dict

    @w_forecast_dict.setter
    def w_forecast_dict(self, value):
        # check type
        try:
            value = dict(value)
            # since json fmt doesn't allow this: ensure key are python int (not str)
            value = {int(k): v for k, v in value.items()}
        except (TypeError, ValueError):
            value = None
        # check change
        if self._w_forecast_dict != value:
            self._w_forecast_dict = value
            self._on_forecast_change()

    def _on_today_change(self):
        # set today date
        self.frm_today.configure(text=datetime.now().date())
        # fill labels
        try:
            # today
            today_desc = self._w_today_dict["description"]
            today_t = self._w_today_dict["t"]
            today_t_min = self._w_today_dict["t_min"]
            today_t_max = self._w_today_dict["t_max"]
            # today message
            message = "Situation : %s\n\nTempérature actuelle : %d°C\n" + \
                      "            minimale : %d°C\n" + \
                      "            maximale : %d°C"
            message %= (today_desc, today_t, today_t_min, today_t_max)
            self.lbl_today.configure(text=message)
        except:
            self.lbl_today.configure(text="n/a")
            logging.error(traceback.format_exc())

    def _on_forecast_change(self):
        # set day 1 to 4 date
        for i in range(4):
            self._days_f_l[i].configure(text=datetime.now().date() + timedelta(days=i + 1))
        try:
            # for day 1 to 4
            for d in range(1, 5):
                day_desr = self._w_forecast_dict[d]["description"]
                day_t_min = self._w_forecast_dict[d]["t_min"]
                day_t_max = self._w_forecast_dict[d]["t_max"]
                # set day message
                message = "%s\n\nT min %d°C\nT max %d°C"
                message %= (day_desr, day_t_min, day_t_max)
                self._days_lbl[d - 1].configure(text=message)
        except:
            # for day 1 to 4
            for d in range(1, 5):
                self._days_lbl[d - 1].configure(text="n/a")
            logging.error(traceback.format_exc())


class ClockTile(Tile):
    def __init__(self, *args, **kwargs):
        Tile.__init__(self, *args, **kwargs)
        # public
        # private
        self._date_str = tk.StringVar()
        self._time_str = tk.StringVar()
        # set locale (for french day name)
        locale.setlocale(locale.LC_ALL, "fr_FR.UTF-8")
        # tk stuff
        tk.Label(self, textvariable=self._date_str, font=('bold', 15), bg=self.cget("bg"), anchor=tk.W,
                 justify=tk.LEFT).pack(expand=True)
        tk.Label(self, textvariable=self._time_str, font=('digital-7', 30), bg=self.cget("bg"),
                 fg='green').pack(expand=True)
        # auto-update clock
        self.start_cyclic_update(update_ms=500)

    def update(self):
        self._date_str.set(datetime.now().strftime('%A %d %B %Y'))
        self._time_str.set(datetime.now().strftime('%H:%M:%S'))


class NewsBannerTile(Tile):
    BAN_MAX_NB_CHAR = 50

    def __init__(self, *args, **kwargs):
        Tile.__init__(self, *args, **kwargs)
        # public
        self.ban_nb_char = NewsBannerTile.BAN_MAX_NB_CHAR
        # private
        self._l_titles = []
        self._lbl_ban = tk.StringVar()
        self._next_ban_str = ""
        self._disp_ban_str = ""
        self._disp_ban_pos = 0
        # tk stuff
        # set yellow background for this tile
        self.configure(bg="yellow")
        # use a proportional font to handle spaces correctly, height is nb of lines
        tk.Label(self, textvariable=self._lbl_ban, height=1,
                 bg=self.cget("bg"), font=('courier', 51, 'bold')).pack(expand=True)
        # auto-update clock
        self.start_cyclic_update(update_ms=200)

    @property
    def l_titles(self):
        return self._l_titles

    @l_titles.setter
    def l_titles(self, value):
        # check type
        try:
            value = list(value)
        except (TypeError, ValueError):
            value = None
        # check change
        if self._l_titles != value:
            # check range
            self._l_titles = value
            # update widget
            self._on_data_change()

    def update(self):
        # scroll text on screen
        # start a new scroll ?
        if self._disp_ban_pos >= len(self._disp_ban_str) - self.ban_nb_char:
            # update display scroll message
            self._disp_ban_str = self._next_ban_str
            self._disp_ban_pos = 0
        scroll_view = self._disp_ban_str[self._disp_ban_pos:self._disp_ban_pos + self.ban_nb_char]
        self._lbl_ban.set(scroll_view)
        self._disp_ban_pos += 1

    def _on_data_change(self):
        spaces_head = " " * self.ban_nb_char
        try:
            # update banner
            self._next_ban_str = spaces_head
            for title in self._l_titles:
                self._next_ban_str += title + spaces_head
        except TypeError:
            self._next_ban_str = spaces_head + "n/a" + spaces_head
        except:
            self._next_ban_str = spaces_head + "n/a" + spaces_head
            logging.error(traceback.format_exc())


class PdfOpenerTile(Tile):
    def __init__(self, *args, file, **kwargs):
        Tile.__init__(self, *args, **kwargs)
        # public
        self.file = file
        self.filename = os.path.basename(file)
        # private
        self._l_process = list()
        # tk stuff
        self.name = tk.Label(self, text=os.path.splitext(self.filename)[0], wraplength=550,
                             bg=self.cget("bg"), font=("courrier", 20, "bold"))
        self.name.pack(expand=True)
        # bind function for open pdf file
        self.bind("<Button-1>", self._on_click)
        self.name.bind("<Button-1>", self._on_click)
        self.bind("<Unmap>", self._on_unmap)

    def _on_click(self, evt=None):
        try:
            # start xpdf for this pdf file (max 2 instance)
            if len(self._l_process) < 2:
                xpdf_geometry = "-geometry %sx%s" % (self.master.winfo_width(), self.master.winfo_height() - 10)
                self._l_process.append(subprocess.Popen(["/usr/bin/xpdf", xpdf_geometry, "-z page", "-cont", self.file],
                                                        stdin=subprocess.DEVNULL,
                                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                                        close_fds=True))
        except Exception:
            logging.error(traceback.format_exc())

    def _on_unmap(self, evt=None):
        # clean all running process on tab exit
        for i, _ in enumerate(self._l_process):
            self._l_process[i].terminate()
            # avoid zombie process
            self._l_process[i].wait()
            del self._l_process[i]


class MeetingRoomTile(Tile):
    def __init__(self, *args, room, **kwargs):
        Tile.__init__(self, *args, **kwargs)
        # public

        # private
        self._status = None
        self._status_str = tk.StringVar()
        self._status_str.set('n/a')
        # tk stuff
        # init a 3x3 grid
        for r in range(3):
            for c in range(3):
                self.grid_columnconfigure(c, weight=1)
                tk.Label(self, bg=self.cget("bg")).grid(row=r, column=c)
            self.grid_rowconfigure(r, weight=1)
        # set labels
        tk.Label(self, text=room, bg=self.cget("bg"), font="bold",
                 justify="left", anchor="w").grid(row=1, column=0, sticky=tk.NSEW)
        tk.Label(self, textvariable=self._status_str, bg=self.cget("bg"), font="bold", justify="left",
                 anchor="w").grid(row=2, column=0, sticky=tk.NSEW)
        self.tk_img = tk.PhotoImage()
        tk.Label(self, image=self.tk_img, bg=self.cget("bg")).grid(row=0, column=2, rowspan=3)

    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, value):
        # check type
        try:
            value = str(value)
        except (TypeError, ValueError):
            value = None
        # check change
        if self._status != value:
            # check range
            self._status = value
            # update widget
            self._on_data_change()

    def _on_data_change(self):
        if self._status is not None:
            # set status on screen
            self._status_str.set(self._status)
            try:
                # set traffic light image
                if self._status == "Occ" or self._status == "OccPeriod":
                    self.tk_img.configure(file=IMG_PATH + "tf_red.png")
                elif self._status == "Unocc":
                    self.tk_img.configure(file=IMG_PATH + "tf_orange.png")
                elif self._status == "UnoccRepeat":
                    self.tk_img.configure(file=IMG_PATH + "tf_green.png")
            except Exception:
                logging.error(traceback.format_exc())


class GaugeTile(Tile):
    GAUGE_MIN = 0.0
    GAUGE_MAX = 100.0

    def __init__(self, *args, title, **kwargs):
        Tile.__init__(self, *args, **kwargs)
        # public
        self.title = title
        self.th_orange = 70
        self.th_red = 40
        # private
        self._str_title = tk.StringVar()
        self._str_title.set(self.title)
        self._head_str = ""
        self._percent = None
        # tk build
        self.label = tk.Label(self, textvariable=self._str_title, font='bold')
        self.label.grid(sticky=tk.NSEW)
        self.can = tk.Canvas(self, width=220, height=110, borderwidth=2, relief='sunken', bg='white')
        self.can.grid()
        self.can_arrow = self.can.create_line(100, 100, 10, 100, fill='grey', width=3, arrow='last')
        self.can.lower(self.can_arrow)
        self.can.create_arc(20, 10, 200, 200, extent=108, start=36, style='arc', outline='black')

    @property
    def percent(self):
        return self._percent

    @percent.setter
    def percent(self, value):
        # check type
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = None
        # check change
        if self._percent != value:
            # check range
            self._percent = value
            # update widget
            self._on_data_change()

    @property
    def header_str(self):
        return self._head_str

    @header_str.setter
    def header_str(self, value):
        # check type
        try:
            value = str(value)
        except (TypeError, ValueError):
            value = ""
        # check change
        if self._head_str != value:
            # check range
            self._head_str = value
            # update widget
            self._on_data_change()

    def _on_data_change(self):
        # update widget
        try:
            # convert value
            ratio = (self._percent - self.GAUGE_MIN) / (self.GAUGE_MAX - self.GAUGE_MIN)
            ratio = min(ratio, 1.0)
            ratio = max(ratio, 0.0)
            # set arrow on widget
            self._set_arrow(ratio)
            # update alarm, warn, fine status
            if self._percent < self.th_red:
                self.can.configure(bg="red")
            elif self._percent < self.th_orange:
                self.can.configure(bg="orange")
            else:
                self.can.configure(bg="green")
            if self._head_str:
                self._str_title.set("%s (%s)" % (self.title, self._head_str))
            else:
                self._str_title.set("%s (%.1f %%)" % (self.title, self.percent))
        except (TypeError, ZeroDivisionError):
            self._set_arrow(0.0)
            self.can.configure(bg="pink")
            self._str_title.set("%s (%s)" % (self.title, "N/A"))

    def _set_arrow(self, ratio):
        # normalize ratio : 0.2 to 0.8
        ratio = ratio * 0.6 + 0.2
        # compute arrow head
        x = 112 - 90 * math.cos(ratio * math.pi)
        y = 100 - 90 * math.sin(ratio * math.pi)
        # update canvas
        self.can.coords(self.can_arrow, 112, 100, x, y)


class DaysAccTile(Tile):
    def __init__(self, *args, **kwargs):
        Tile.__init__(self, *args, **kwargs)
        # public
        # private
        self._acc_date_dts = None
        self._acc_date_digne = None
        self._days_dts_str = tk.StringVar()
        self._days_digne_str = tk.StringVar()
        # tk stuff
        self.configure(bg="white")
        # populate tile with blank grid parts
        for c in range(3):
            for r in range(3):
                self.grid_rowconfigure(r, weight=1)
                if c > 0:
                    tk.Label(self, bg="white").grid(row=r, column=c, )
            self.columnconfigure(c, weight=1)
        # add label
        tk.Label(self, text="La sécurité est notre priorité !",
                 font=('courier', 20, 'bold'), bg="white").grid(row=0, column=0, columnspan=2)
        # DTS
        tk.Label(self, textvariable=self._days_dts_str, font=('courier', 24, 'bold'),
                 fg=FUSHIA, bg=self.cget("bg")).grid(row=1, column=0)
        tk.Label(self, text="Jours sans accident DTS",
                 font=('courier', 18, 'bold'), bg=self.cget("bg")).grid(row=1, column=1, sticky=tk.W)
        # DIGNE
        tk.Label(self, textvariable=self._days_digne_str, font=('courier', 24, 'bold'),
                 fg=FUSHIA, bg=self.cget("bg")).grid(row=2, column=0)
        tk.Label(self, text="Jours sans accident DIGNE",
                 font=('courier', 18, 'bold'), bg=self.cget("bg")).grid(row=2, column=1, sticky=tk.W)
        # auto-update acc day counter
        self.start_cyclic_update(update_ms=5000)

    @property
    def acc_date_dts(self):
        return self._acc_date_dts

    @acc_date_dts.setter
    def acc_date_dts(self, value):
        # check type
        try:
            value = str(value)
        except (TypeError, ValueError):
            value = None
        # check change
        if self._acc_date_dts != value:
            # check range
            self._acc_date_dts = value
            # update widget
            self.update()

    @property
    def acc_date_digne(self):
        return self._acc_date_digne

    @acc_date_digne.setter
    def acc_date_digne(self, value):
        # check type
        try:
            value = str(value)
        except (TypeError, ValueError):
            value = None
        # check change
        if self._acc_date_digne != value:
            # check range
            self._acc_date_digne = value
            # update widget
            self.update()

    def update(self):
        self._days_dts_str.set(self.day_from_now(self._acc_date_dts))
        self._days_digne_str.set(self.day_from_now(self._acc_date_digne))

    @staticmethod
    def day_from_now(date_str):
        try:
            day, month, year = map(int, str(date_str).split('/'))
            return str((datetime.now() - datetime(year, month, day)).days)
        except Exception:
            return "n/a"


class ImageTile(Tile):
    def __init__(self, *args, file="", img_ratio=1, **kwargs):
        Tile.__init__(self, *args, **kwargs)
        # tk job
        self.tk_img = tk.PhotoImage()
        self.lbl_img = tk.Label(self, bg=self.cget("bg"))
        self.lbl_img.pack(expand=True)
        # display current image file
        try:
            # set file path
            self.tk_img.configure(file=file)
            # set image with resize ratio (if need)
            self.tk_img = self.tk_img.subsample(img_ratio)
            self.lbl_img.configure(image=self.tk_img)
        except Exception:
            logging.error(traceback.format_exc())


class ImageRefreshTile(Tile):
    def __init__(self, *args, file, img_ratio=1, refresh_rate=5000, **kwargs):
        Tile.__init__(self, *args, **kwargs)
        # public
        self.file = file
        self.img_ratio = img_ratio
        # tk job
        self.tk_img = tk.PhotoImage()
        self.lbl_img = tk.Label(self, bg=self.cget("bg"))
        self.lbl_img.pack(expand=True)
        # auto-update clock
        self.start_cyclic_update(update_ms=refresh_rate)

    def update(self):
        # display current image file
        try:
            # set file path
            self.tk_img.configure(file=self.file)
            # set image with resize ratio (if need)
            self.tk_img = self.tk_img.subsample(self.img_ratio)
            self.lbl_img.configure(image=self.tk_img)
        except Exception:
            logging.error(traceback.format_exc())


class ImageCarouselTile(Tile):
    def __init__(self, *args, refresh_rate=20000, **kwargs):
        Tile.__init__(self, *args, **kwargs)
        # private
        self._img_index = 0
        self._img_files = list()
        # tk job
        self.configure(bg="white")
        self.tk_img = tk.PhotoImage()
        self.lbl_img = tk.Label(self, image=self.tk_img)
        self.lbl_img.pack(expand=True)
        # first img load
        self._img_files_reload()
        # auto-update carousel rotate
        self.start_cyclic_update(update_ms=refresh_rate)

    def update(self):
        # next img file index
        self._img_index += 1
        if self._img_index >= len(self._img_files):
            self._img_index = 0
            self._img_files_reload()
        # display current image file
        try:
            self.tk_img.configure(file=self._img_files[self._img_index])
        except Exception:
            logging.error(traceback.format_exc())

    def _img_files_reload(self):
        self._img_files = glob.glob(DOC_PATH + "*.png")


# main
if __name__ == "__main__":
    # logging setup
    logging.basicConfig(format='%(asctime)s %(message)s', level=logging.DEBUG)
    # start IO thread
    threading.Thread(target=Tags.tags_io_thread, daemon=True).start()
    # start tkinter
    app = MainApp()
    app.title('GRTgaz Dashboard')
    app.attributes('-fullscreen', True)
    app.mainloop()

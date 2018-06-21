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
# gmap img traffic
gmap_img_target = cnf.get("gmap_img", "img_target")


class DS:
    # create connector
    r = redis.StrictRedis(host="192.168.0.60", socket_timeout=5, socket_keepalive=True)

    # redis access method
    @classmethod
    def redis_get(cls, name):
        try:
            return cls.r.get(name).decode('utf-8')
        except (redis.RedisError, AttributeError):
            return None

    @classmethod
    def redis_get_obj(cls, name):
        try:
            return json.loads(cls.r.get(name).decode('utf-8'))
        except (redis.RedisError, AttributeError, json.decoder.JSONDecodeError):
            return None


class Tag:
    all_tags = []

    def __init__(self, init=None, cmd_src=None):
        # private
        self._var = init
        self._subscribers = []
        self._cmd_src = cmd_src
        # first update
        self.update()
        # record the tag in tags list
        Tag.all_tags.append(self)

    def __repr__(self):
        return repr(self._var)

    def update(self):
        if self._cmd_src:
            self.var = self._cmd_src()

    @property
    def var(self):
        return self._var

    @var.setter
    def var(self, value):
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
    D_GSHEET_GRT = Tag(cmd_src=lambda: DS.redis_get_obj("gsheet:grt"))
    D_ISWIP_ROOM = Tag(cmd_src=lambda: DS.redis_get_obj("iswip:room_status"))
    D_GMAP_TRAFFIC = Tag(cmd_src=lambda: DS.redis_get_obj("gmap:traffic"))

    @classmethod
    def update(cls):
        # for tag auto-update method (with cmd_srv)
        Tag.update_all()


class MainApp(tk.Tk):
    def __init__(self, *args, **kwargs):
        tk.Tk.__init__(self, *args, **kwargs)
        # define style to fix size of tab header
        self.style = ttk.Style()
        self.style.theme_settings("default",
                                  {"TNotebook.Tab": {"configure": {"padding": [TAB_PAD_WIDTH, TAB_PAD_HEIGHT]}}})
        # define notebook
        self.note = ttk.Notebook(self)
        self.tab1 = LiveTab(self.note)
        self.tab2 = DocTab(self.note)
        self.note.add(self.tab1, text="Tableau de bord")
        self.note.add(self.tab2, text="Affichage réglementaire")
        # default tab
        # self.note.grid(row=0, column=0, rowspan=1, columnspan=20, sticky=tk.NSEW)
        # self.note.grid_columnconfigure(0, minsize=1940)
        # self.note.place(in_=self, anchor="c", relx=.5, rely=.5)
        #  self.note.pack(fill=tk.BOTH, expand=True)
        self.note.pack()
        self.note.select(self.tab1)
        # press Esc to quit
        self.bind("<Escape>", lambda e: self.destroy())
        # bind function keys to tabs
        self.bind("<F1>", lambda evt: self.note.select(self.tab1))
        self.bind("<F2>", lambda evt: self.note.select(self.tab2))


class Tab(tk.Frame):
    """
    Base Tab class, with a frame full of tile, can be derived as you need it
    """

    def __init__(self, *args, **kwargs):
        tk.Frame.__init__(self, *args, **kwargs)
        self.screen_width = self.winfo_screenwidth()
        self.number_of_tile_width = 17
        self.screen_height = self.winfo_screenheight() - 60
        self.number_of_tile_height = 9
        self.general_padx = round(self.screen_width / (self.number_of_tile_width * 2))
        self.general_pady = round((self.screen_height - TAB_PAD_HEIGHT) / (self.number_of_tile_height * 2))

        # populate the grid with all tiles
        for c in range(0, self.number_of_tile_width):
            for r in range(0, self.number_of_tile_height):
                self.grid_rowconfigure(r, weight=1)
                # Create Labels to space all of it:
                tk.Label(self, pady=self.general_pady, padx=self.general_padx).grid(column=c, row=r)
                Tile(self).set_tile(row=r, column=c)  # see ? we can print simple time
            self.grid_columnconfigure(c, weight=1)  # auto ajust all the columns

        # bind the visibility event, if you clik on the tab to show it, you get the consequences
        self.bind('<Visibility>', lambda evt: self.tab_update())

        self.update_inc = 0
        self.tick = 200
        self._tab_update()

    def _tab_update(self):
        if self.winfo_ismapped():
            self.tab_update()
        self.after(self.tick, self._tab_update)

    def tab_update(self):
        if self.winfo_ismapped():
            self.update_inc += 1

        if self.update_inc >= 5 * 60 * 1:  # 5 minutes
            pass


class LiveTab(Tab):
    """
    First Tab, which is the hottest from all of them
    Damn
    """

    def __init__(self, *args, **kwargs):
        Tab.__init__(self, *args, **kwargs)
        # create all tiles for this tab here
        # traffic Amiens
        self.tl_tf_ami = TrafficDurationTile(self, to_city="Amiens")
        self.tl_tf_ami.set_tile(row=0, column=0)
        # traffic Arras
        self.tl_tf_arr = TrafficDurationTile(self, to_city="Arras")
        self.tl_tf_arr.set_tile(row=0, column=1)
        # traffic Dunkerque
        self.tl_tf_dunk = TrafficDurationTile(self, to_city="Dunkerque")
        self.tl_tf_dunk.set_tile(row=0, column=2)
        # traffic Maubeuge
        self.tl_tf_maub = TrafficDurationTile(self, to_city="Maubeuge")
        self.tl_tf_maub.set_tile(row=0, column=3)
        # traffic Valenciennes
        self.tl_tf_vale = TrafficDurationTile(self, to_city="Valenciennes")
        self.tl_tf_vale.set_tile(row=0, column=4)
        # traffic map
        self.tl_tf_map = TrafficMapTile(self, file=gmap_img_target, img_ratio=2)
        self.tl_tf_map.set_tile(row=1, column=0, rowspan=3, columnspan=5)
        # weather
        self.tl_weath = Weather_Tile(self, destination="Loos")
        self.tl_weath.set_tile(row=0, column=13, rowspan=3, columnspan=4)
        # clock
        self.tl_clock = TimeTile(self)
        self.tl_clock.set_tile(row=0, column=5, rowspan=2, columnspan=3)
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
        # meeting room
        self.tl_room_prj = MeetingRoomTile(self, room="Salle project")
        self.tl_room_prj.set_tile(row=5, column=0, columnspan=2)
        self.tl_room_trn = MeetingRoomTile(self, room="Salle trainning")
        self.tl_room_trn.set_tile(row=6, column=0, columnspan=2)
        self.tl_room_met = MeetingRoomTile(self, room="Salle meeting")
        self.tl_room_met.set_tile(row=7, column=0, columnspan=2)
        self.tl_room_bur1 = MeetingRoomTile(self, room="Bureau passage 1")
        self.tl_room_bur1.set_tile(row=5, column=2, columnspan=2)
        self.tl_room_bur2 = MeetingRoomTile(self, room="Bureau passage 2")
        self.tl_room_bur2.set_tile(row=6, column=2, columnspan=2)
        # acc days stat
        self.tl_acc = DaysFromAccident(self)
        self.tl_acc.set_tile(row=0, column=8, columnspan=5, rowspan=2)
        # logo img
        self.tl_img_logo = ImageTile(self, file=IMG_PATH + "logo.png")
        self.tl_img_logo.set_tile(row=6, column=13, rowspan=2, columnspan=4)
        # caroussel
        self.tl_crl = CarousselTile(self)
        self.tl_crl.set_tile(row=4, column=7, rowspan=4, columnspan=6)
        # init counter
        self.update_inc = 0

    def tab_update(self):
        # some update stuff to do when this tab is mapped
        # every 5 min
        if (self.update_inc % (5 * 60 * 5)) == 0:
            # acc days stat
            self.tl_acc.acc_date_dts = Tags.D_GSHEET_GRT.get("DATE_ACC_DTS")
            self.tl_acc.acc_date_digne = Tags.D_GSHEET_GRT.get("DATE_ACC_DIGNE")
            # weather
            self.tl_weath.update()

        # every 20s
        if (self.update_inc % (5 * 20)) == 0:
            # update all defined tags
            Tags.update()
            # traffic map
            self.tl_tf_map.update()
            # Amiens
            self.tl_tf_ami.travel_t = Tags.D_GMAP_TRAFFIC.get(("Amiens", "duration"))
            self.tl_tf_ami.traffic_t = Tags.D_GMAP_TRAFFIC.get(("Amiens", "duration_traffic"))
            # Arras
            self.tl_tf_arr.travel_t = Tags.D_GMAP_TRAFFIC.get(("Arras", "duration"))
            self.tl_tf_arr.traffic_t = Tags.D_GMAP_TRAFFIC.get(("Arras", "duration_traffic"))
            # Dunkerque
            self.tl_tf_dunk.travel_t = Tags.D_GMAP_TRAFFIC.get(("Dunkerque", "duration"))
            self.tl_tf_dunk.traffic_t = Tags.D_GMAP_TRAFFIC.get(("Dunkerque", "duration_traffic"))
            # Maubeuge
            self.tl_tf_maub.travel_t = Tags.D_GMAP_TRAFFIC.get(("Maubeuge", "duration"))
            self.tl_tf_maub.traffic_t = Tags.D_GMAP_TRAFFIC.get(("Maubeuge", "duration_traffic"))
            # Valenciennes
            self.tl_tf_vale.travel_t = Tags.D_GMAP_TRAFFIC.get(("Valenciennes", "duration"))
            self.tl_tf_vale.traffic_t = Tags.D_GMAP_TRAFFIC.get(("Valenciennes", "duration_traffic"))
            # update news widget
            self.tl_news.l_titles = DS.redis_get_obj("news:local")
            # carousel update
            self.tl_crl.update()
            # gauges update
            self.tl_g_veh.percent = Tags.D_GSHEET_GRT.get("IGP_VEH_JAUGE_DTS")
            self.tl_g_veh.header_str = "%s/%s" % (Tags.D_GSHEET_GRT.get("IGP_VEH_REAL_DTS"),
                                                  Tags.D_GSHEET_GRT.get("IGP_VEH_OBJ_DTS"))
            self.tl_g_loc.percent = Tags.D_GSHEET_GRT.get("IGP_LOC_JAUGE_DTS")
            self.tl_g_loc.header_str = "%s/%s" % (Tags.D_GSHEET_GRT.get("IGP_LOC_REAL_DTS"),
                                                  Tags.D_GSHEET_GRT.get("IGP_LOC_OBJ_DTS"))
            self.tl_g_req.percent = Tags.D_GSHEET_GRT.get("R_EQU_JAUGE_DTS")
            self.tl_g_req.header_str = "%s/%s" % (Tags.D_GSHEET_GRT.get("R_EQU_REAL_DTS"),
                                                  Tags.D_GSHEET_GRT.get("R_EQU_OBJ_DTS"))
            self.tl_g_vcs.percent = Tags.D_GSHEET_GRT.get("VCS_JAUGE_DTS")
            self.tl_g_vcs.header_str = "%s/%s" % (Tags.D_GSHEET_GRT.get("VCS_REAL_DTS"),
                                                  Tags.D_GSHEET_GRT.get("VCS_OBJ_DTS"))
            self.tl_g_vst.percent = Tags.D_GSHEET_GRT.get("VST_JAUGE_DTS")
            self.tl_g_vst.header_str = "%s/%s" % (Tags.D_GSHEET_GRT.get("VST_REAL_DTS"),
                                                  Tags.D_GSHEET_GRT.get("VST_OBJ_DTS"))
            self.tl_g_qsc.percent = Tags.D_GSHEET_GRT.get("Q_HRE_JAUGE_DTS")
            self.tl_g_qsc.header_str = "%s/%s" % (Tags.D_GSHEET_GRT.get("Q_HRE_REAL_DTS"),
                                                  Tags.D_GSHEET_GRT.get("Q_HRE_OBJ_DTS"))
            # update room status
            self.tl_room_trn.status = Tags.D_ISWIP_ROOM.get("Salle_TRAINNING")
            self.tl_room_prj.status = Tags.D_ISWIP_ROOM.get("Salle_PROJECT")
            self.tl_room_met.status = Tags.D_ISWIP_ROOM.get("Salle_MEETING")
            self.tl_room_bur1.status = Tags.D_ISWIP_ROOM.get("Bureau_Passage_1")
            self.tl_room_bur2.status = Tags.D_ISWIP_ROOM.get("Bureau_Passage_2")
        # every 0.2s
        if (self.update_inc % 1) == 0:
            # update clock
            self.tl_clock.update()
            # update news banner
            self.tl_news.update()
        self.update_inc += 1


class DocTab(Tab):
    def __init__(self, *args, **kwargs):
        Tab.__init__(self, *args, **kwargs)
        self.tiles = dict()
        self.tiles["pdfs"] = list()
        self.bind('<Visibility>', lambda evt: self.tab_update())
        self.old = ""

    # dynamic update of the pdf files in the cold page
    def tab_update(self):
        try:
            # list all PDF availables
            current_pdf = glob.glob(PDF_PATH + "*.pdf")

            # if there is any difference in the pdf list, REFRESH, else don't, there is no need
            if current_pdf != self.old:
                for pdf in self.tiles["pdfs"]:
                    pdf.set_tile(remove=True)
                    pdf.destroy()
                self.tiles["pdfs"] = list()
                r = 1
                c = 1
                for file in current_pdf:
                    self.tiles["pdfs"].append(
                        Pdf_Tile(self, file=file))
                    self.tiles["pdfs"][-1].set_tile(row=r, column=c, columnspan=2, rowspan=2)
                    c = (c + 2)
                    if c >= self.number_of_tile_width - 1:
                        r += 2
                        c = 1
            self.old = current_pdf
        except Exception:
            logging.error(traceback.format_exc())


class Tile(tk.Frame):
    """
    Source of all the tile here
    Default : a gray, black bordered, case
    """
    def __init__(self, *args, **kwargs):
        tk.Frame.__init__(self, *args, **kwargs)
        # force Frame attribute
        self.configure(bg=VERT)
        self.configure(highlightbackground=ARDOISE)
        self.configure(highlightthickness=3)
        self.configure(bd=0)

    def set_tile(self, row=0, column=0, rowspan=1, columnspan=1, remove=None):
        # function to print a tile on the screen at the given coordonates
        if remove:
            self.grid_remove()
        else:
            self.grid(row=row, column=column, rowspan=rowspan, columnspan=columnspan, sticky=tk.NSEW)
            # deny frame resize
            self.grid_propagate(False)

    def update(self):
        pass


class TrafficDurationTile(Tile):  # traffic duration #json
    def __init__(self, *args, to_city, **kwargs):
        Tile.__init__(self, *args, **kwargs)
        # public
        self.to_city = to_city
        # private
        self._travel_t = 0
        self._traffic_t = 0
        self._traffic_str = tk.StringVar()
        self._t_inc_str = tk.StringVar()
        self._traffic_str.set("N/A")
        self._t_inc_str.set("N/A")
        # tk job
        tk.Label(self, text=to_city, font="bold").pack()
        tk.Label(self).pack()
        tk.Label(self, textvariable=self._traffic_str).pack()
        tk.Label(self, textvariable=self._t_inc_str).pack()

    @property
    def travel_t(self):
        return self._travel_t

    @travel_t.setter
    def travel_t(self, value):
        # check type
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = None
        # check change
        if self._travel_t != value:
            self._travel_t = value
            self._on_data_change()

    @property
    def traffic_t(self):
        return self._travel_t

    @traffic_t.setter
    def traffic_t(self, value):
        # check type
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = None
        # check change
        if self._traffic_t != value:
            self._traffic_t = value
            self._on_data_change()

    def _on_data_change(self):
        try:
            t_increase = self._traffic_t - self._travel_t
            t_increase_ratio = t_increase / self._travel_t
        except (TypeError, ZeroDivisionError):
            # set tk var
            self._traffic_str.set("N/A")
            self._t_inc_str.set("N/A")
            # choose tile color
            tile_color = "pink"
        else:
            # set tk var
            self._traffic_str.set("%.0f mn" % (self._traffic_t / 60))
            self._t_inc_str.set("%+.0f mn" % (t_increase / 60))
            # choose tile color
            tile_color = "green"
            if t_increase_ratio > 0.35:
                tile_color = "red"
            elif t_increase_ratio > 0.10:
                tile_color = "orange"
        # update tile and his childs color
        for w in self.winfo_children():
            w.configure(bg=tile_color)
        self.configure(bg=tile_color)


class Weather_Tile(Tile):  # principal, she own all the day, could be divided if wanted #json
    def __init__(self, *args, destination="Loos", **kwargs):
        Tile.__init__(self, *args, **kwargs)

        # here lay the color background in function of the main weather
        self.weathercolor = {"Thinderstorm": "Yellow",
                             "Drizzle": "light steel blue",
                             "Rain": "steel blue",
                             "Snow": "snow",
                             "Atmosphere": "lavender",
                             "Clear": "deep sky blue",
                             "Clouds": "gray",
                             "Extreme": "red",
                             "Additional": "green"}
        self.destination = destination

        ### other 4 days of the week ###
        ## init ##
        self.days = list()  # LabelFrame x4 (des jours de la semaine)
        self.dayslabel = list()  # Label x4 (le descriptif des jours de la semaine)
        self.daysicone = list()  # PhotoImage x4 (les images / icones des journées ex:Soleil -> ../images/01d.png)
        self.daysiconelabel = list()  # Label x4  (les label qui contiennent les image )
        # end init

        for c in range(4):  # pour chaque colonne
            for r in range(3):  # pour chaque ligne
                # Create Labels to space all of it:
                self.grid_rowconfigure(r, weight=1)  # auto ajust all the rows
                tk.Label(master=self, pady=0, padx=0, background="gray").grid(column=c, row=r)

            self.grid_columnconfigure(c, weight=1)  # auto ajust all the columns
            ## creation ##
            self.days.append(tk.LabelFrame(master=self, text="dd/mm/yyyy", bg="yellow", font=("bold", 10)))
            self.dayslabel.append(
                tk.Label(master=self.days[c], text="empty", font='bold', anchor=tk.W, justify=tk.LEFT))
            self.daysicone.append(tk.PhotoImage())
            self.daysiconelabel.append(tk.Label(master=self.days[c], image=self.daysicone[c]))
            # end creation
            ## impression ##
            self.days[c].grid(row=2, column=c, sticky=tk.NSEW)
            self.days[c].grid_propagate(False)

            self.dayslabel[c].grid(sticky=tk.NSEW)
            self.dayslabel[c].grid_propagate(False)  # idem

            self.daysiconelabel[c].grid(sticky=tk.NSEW)  # on imprime les images
            # end impression
            # end other 4 days of the week

        # Today
        self.todayframe = tk.LabelFrame(master=self, bg="red", text="Today :", font=("bold", 20))  # today title
        self.todaylabel = tk.Label(master=self.todayframe, text="empty", font=('courier', 18, 'bold'), anchor=tk.W,
                                   justify=tk.LEFT)  # today weather
        self.todayicone = tk.PhotoImage()  # today icone

        self.todayframe.grid(row=0, column=0, columnspan=4, rowspan=2, sticky=tk.NSEW)
        self.todayframe.grid_propagate(False)
        self.todaylabel.grid(column=0)
        self.todaylabel.grid_propagate(False)
        self.todayiconelabel = tk.Label(master=self.todayframe, image=self.todayicone, bg=self.todayframe.cget("bg"))
        self.todayiconelabel.grid(row=1)

    def update(self):
        """
        update function, 7200 call per day maximum
        """
        self.todayframe.configure(text=datetime.now().date())  # le labelframe du jour affiche la bonne date

        for i in range(4):
            self.days[i].configure(
                text=datetime.now().date() + timedelta(days=i + 1))  # chaque tuile des autres jours aussi

        try:
            # TODAY
            # text of the Today cell
            today_mood = str(DS.r.get("Weather." + self.destination + ".Today.mood").decode("utf-8"))
            today_desc = str(DS.r.get("Weather." + self.destination + ".Today.description").decode("utf-8"))
            today_t = float(DS.r.get("Weather." + self.destination + ".Today.temp").decode("utf-8"))
            today_t_min = float(DS.r.get("Weather." + self.destination + ".Today.temp_min").decode("utf-8"))
            today_t_max = float(DS.r.get("Weather." + self.destination + ".Today.temp_max").decode("utf-8"))
            message = "Today's mood : %s\nDescription : %s\nTempérature actuelle : %.1f°C\n" + \
                      "            minimale : %.1f°C\n" + \
                      "            maximale : %.1f°C"
            message %= (today_mood, today_desc, today_t, today_t_min, today_t_max)
            self.todaylabel.configure(text=message)  # stiick the text to the left
            self.todayframe.configure(
                bg=self.weathercolor[DS.r.get("Weather." + self.destination + ".Today.mood").decode("utf-8")])
            self.todaylabel.configure(
                bg=self.todayframe.cget("bg"))  # to get the TodayFrame bg attribute, to use on the childer frame
            self.todayiconelabel.configure(bg=self.todayframe.cget("bg"))  # same as befor
            self.todayicone.configure(
                file=IMG_PATH + DS.r.get("Weather." + self.destination + ".Today.icon").decode(
                    "utf-8") + '.png')

            for inc in range(1, 5):  # other 4 days, same structure than befor, but simplier, less information needed
                day_mood = str(DS.r.get("Weather." + self.destination + ".Day" + str(inc) + ".mood").decode("utf-8"))
                day_t_min = int(
                    float(DS.r.get("Weather." + self.destination + ".Day" + str(inc) + ".temp_min").decode("utf-8")))
                day_t_max = int(
                    float(DS.r.get("Weather." + self.destination + ".Day" + str(inc) + ".temp_max").decode("utf-8")))
                message = "%s\nT mini %d°C\nT maxi %d°C"
                message %= (day_mood, day_t_min, day_t_max)
                self.dayslabel[inc - 1].configure(text=message)
                self.days[inc - 1].configure(bg=self.weathercolor[
                    DS.r.get("Weather." + self.destination + ".Day" + str(inc) + ".mood").decode("utf-8")])
                self.dayslabel[inc - 1].configure(bg=self.days[inc - 1].cget("bg"))
                self.daysicone[inc - 1].configure(file=IMG_PATH + DS.r.get(
                    "Weather." + self.destination + ".Day" + str(inc) + ".icon").decode("utf-8") + ".png")
                self.daysiconelabel[inc - 1].configure(bg=self.days[inc - 1].cget("bg"))
                inc += 1
        except Exception:
            logging.error(traceback.format_exc())


class TimeTile(Tile):
    def __init__(self, *args, **kwargs):
        Tile.__init__(self, *args, **kwargs)
        # public
        # private
        self._date_str = tk.StringVar()
        self._time_str = tk.StringVar()
        # set locale (for french day name)
        locale.setlocale(locale.LC_ALL, "fr_FR.UTF-8")
        # tk stuff
        # init 3x3 grid
        for r in range(3):
            for c in range(3):
                self.grid_columnconfigure(c, weight=1)
                tk.Label(self, bg=self.cget("bg")).grid(row=r, column=c)
            self.grid_rowconfigure(r, weight=1)
        # add labels
        tk.Label(self, textvariable=self._date_str, font=('bold', 15) , bg=self.cget("bg"), anchor=tk.W,
                 justify=tk.LEFT).grid(row=0, column=0, columnspan=3, sticky=tk.NSEW)
        tk.Label(self, textvariable=self._time_str, font=('digital-7', 30), bg=self.cget("bg"),
                 fg='green').grid(row=1, column=1)

    def update(self):
        self._date_str.set(datetime.now().strftime('%A %d/%m/%Y'))
        self._time_str.set(datetime.now().strftime('%H:%M:%S'))


class TrafficMapTile(Tile):  # google map traffic # still need to define
    def __init__(self, *args, file, img_ratio=1, **kwargs):
        Tile.__init__(self, *args, **kwargs)
        # public
        self.file = file
        self.img_ratio = img_ratio
        # tk job
        self.configure(bg="white")
        self.tk_img = tk.PhotoImage()
        self.lbl_img = tk.Label(self, bg="#FFFFFF")
        self.lbl_img.grid()

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


class NewsBannerTile(Tile):
    def __init__(self, *args, **kwargs):
        Tile.__init__(self, *args, **kwargs)
        # public
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
        if self._disp_ban_pos >= len(self._disp_ban_str) - self._get_ban_nb_char():
            # update display scroll message
            self._disp_ban_str = self._next_ban_str
            self._disp_ban_pos = 0
        scroll_view = self._disp_ban_str[self._disp_ban_pos:self._disp_ban_pos + self._get_ban_nb_char()]
        self._lbl_ban.set(scroll_view)
        self._disp_ban_pos += 1

    def _get_ban_nb_char(self):
        # get number of char in current display banner
        #return round(self.winfo_width()/38.36)
        return 50

    def _on_data_change(self):
        spaces_head = " " * self._get_ban_nb_char()
        try:
            # update banner
            self._next_ban_str = spaces_head
            for title in self._l_titles:
                self._next_ban_str += title + spaces_head
        except:
            self._next_ban_str = spaces_head + "n/a" + spaces_head
            logging.error(traceback.format_exc())


# clickable pdf luncher
class Pdf_Tile(Tile):
    def __init__(self, *args, file, **kwargs):
        Tile.__init__(self, *args, **kwargs)
        # public
        self.file = file
        self.filename = os.path.basename(file)
        # tk build
        self.name = tk.Label(self, text=self.filename, wraplength=200, bg=self.cget("bg"),
                             font=("courrier", 20, "bold"))
        self.name.grid()
        self.bind("<Button-1>", self.clicked)
        self.name.bind("<Button-1>", self.clicked)

    def clicked(self, event):
        try:
            subprocess.call(["/usr/bin/xpdf", self.file],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            logging.error(traceback.format_exc())


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


class DaysFromAccident(Tile):
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
        tk.Label(self, text="Safety is number one priority !",
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
            self._on_data_change()

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
            self._on_data_change()

    def _on_data_change(self):
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
    def __init__(self, *args, file=IMG_PATH + "logo.png", img_ratio=1, **kwargs):
        Tile.__init__(self, *args, **kwargs)
        # tk job
        self.configure(bg='white')
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


class CarousselTile(Tile):
    def __init__(self, *args, **kwargs):
        Tile.__init__(self, *args, **kwargs)
        # private
        self._img_index = 0
        self._img_files = list()
        # tk job
        self.configure(bg="white")
        self.tk_img = tk.PhotoImage()
        self.lbl_img = tk.Label(self, image=self.tk_img)
        self.lbl_img.grid()
        # first img load
        self._img_files_reload()

    # call every 20s
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
    # start tkinter
    app = MainApp()
    app.title('GRTgaz Dashboard')
    app.attributes('-fullscreen', True)
    app.mainloop()

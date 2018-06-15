#!/usr/bin/env python3

try:
    # Python 2.x
    import Tkinter as tk
    import ttk
except ImportError:
    # Python 3.x
    import tkinter as tk
    from tkinter import ttk

import logging
import traceback
import redis
from datetime import datetime, timedelta
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
DATA_PATH = "/home/pi/dashboard/"
IMG_PATH = DATA_PATH + "images/"
PDF_PATH = DATA_PATH + "pdf_reglementation/"
DOC_PATH = DATA_PATH + "Document_affichage/"
# GRTgaz Colors
BLEU = "#007bc2"
VERT = "#00a984"
ARDOISE = "#3c4f69"
MARINE = "#154194"
FUSHIA = "#e5007d"
ORANGE = "#f39200"
JAUNE = "#ffe200"


class DS:
    # create connector
    r = redis.StrictRedis(host="192.168.0.60", socket_timeout=5, socket_keepalive=True)

    # redis access method
    @classmethod
    def redis_get(cls, name):
        try:
            return cls.r.get(name)
        except redis.RedisError:
            return None

    @classmethod
    def redis_hgetall(cls, name):
        try:
            return cls.r.hgetall(name)
        except (redis.RedisError, TypeError) as e:
            return None

    @classmethod
    def redis_hmget_one(cls, name, key):
        try:
            return cls.r.hmget(name, key)[0]
        except (redis.RedisError, TypeError) as e:
            return None


class Tag_:
    all_tags = []

    def __init__(self, init=None, cmd_src=None):
        # private
        self._var = init
        self._subscribers = []
        self._cmd_src = cmd_src
        # first update
        self.update()
        # record the tag in tags list
        Tag_.all_tags.append(self)

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

    def set(self, *args):
        self._var.set(*args)


class Tag:
    all_tags = []

    def __init__(self):
        # private
        self._subscribers = []
        # record the tag in tags list
        Tag.all_tags.append(self)

    def update(self):
        pass

    def set(self):
        pass

    def is_update(self):
        for callback in self._subscribers:
            callback(self)

    def subscribe(self, callback):
        # first value
        callback(self)
        # subscribe
        self._subscribers.append(callback)

    @classmethod
    def update_all(cls):
        for tag in cls.all_tags:
            tag.update()


class GaugeTag(Tag):
    def __init__(self, real=0.0, obj=0.0, gauge=0.0):
        super().__init__()
        # public
        self.real = real
        self.obj = obj
        self.gauge = gauge

    def set(self, real=None, obj=None, gauge=None):
        is_changed = False
        if real is not None and real != self.real:
            self.real = float(real)
            is_changed = True
        if obj is not None and obj != self.obj:
            self.real = float(obj)
            is_changed = True
        if gauge is not None and gauge != self.gauge:
            self.gauge = float(gauge)
            is_changed = True
        if is_changed:
            self.is_update()

    def __repr__(self):
        return '%s %s %s ' % (self.real, self.obj, self.gauge)


class Tags:
    # IGP_VEH_JAUGE = Tag_(cmd_src=lambda: DS.redis_hmget_one('grt:gsheet:import', 'IGP_VEH_JAUGE_DTS'))
    # IGP_VEH_REAL = Tag_(cmd_src=lambda: DS.redis_hmget_one('grt:gsheet:import', 'IGP_VEH_REAL_DTS'))
    # IGP_VEH_OBJ = Tag_(cmd_src=lambda: DS.redis_hmget_one('grt:gsheet:import', 'IGP_VEH_OBJ_DTS'))

    @classmethod
    def update_tags(cls):
        # for tag auto-update method (with cmd_srv)
        Tag_.update_all()
        # read google sheet infos
        d_gsheet = DS.redis_hgetall('grt:gsheet:import')
        # if d_gsheet:
        #     # IGP_VEH
        #     cls.IGP_VEH.var.real = d_gsheet.get('IGP_VEH_REAL_DTS', 0.0)


class Application(tk.Frame):
    """
    Main class
    It will be our master, our savior
    It lunch and manage all
    """

    def __init__(self, master=None):
        tk.Frame.__init__(self, master)
        self.master = master
        self.master.grid()
        self.master.grid_propagate(False)
        self.master.title("GRTgaz Dashboard")

        # full screen
        self.master.geometry("{0}x{1}+0+0".format(master.winfo_screenwidth(), master.winfo_screenheight()))
        self.master.focus_set()
        # press Esc to quit
        self.master.bind("<Escape>", lambda e: self.master.destroy())
        # compute to get the width, height of the screen and compute the number of possible tile to put in it
        self.screen_width = self.master.winfo_screenwidth()
        self.number_of_tile_width = self.screen_width // 100
        print(self.number_of_tile_width)
        self.screen_height = self.master.winfo_screenheight()
        self.number_of_tile_height = self.screen_height // 100

        # main notebook
        self.nb = ttk.Notebook(self.master)
        self.nb.grid(row=0, column=0, rowspan=1, columnspan=self.number_of_tile_width, sticky='news')
        # first tab
        self.hotFrame = tk.Label(self.nb)  # page with Hot Data, dynamique and the most interristing ones
        self.nb.add(self.hotFrame, text='\n   Hot Page  \n')  # double \n to expand the tab
        self.page1 = HotTab(self.hotFrame, redis_db=DS.r, nb=self.nb)
        self.page1.grid()
        # second tab
        self.coldFrame = tk.Frame(self.nb)  # it's freezing outside
        self.nb.add(self.coldFrame, text="\n Cooler page \n")  # double \n to expand the tab
        self.page2 = ColdTab(self.coldFrame, nb=self.nb)
        self.page2.grid()


class Tab(tk.Frame):
    """
    Base Tab class, with a frame full of tile, can be derived as you need it
    """

    def __init__(self, master=None, ms=200, redis_db=None, nb=None):
        tk.Frame.__init__(self, master=master, bg=VERT)
        self.nb = nb  # nbbook
        self.redis_db = redis_db
        self.master = master

        self.screen_width = self.master.winfo_screenwidth() - 180  # same as befor, but with some screen ajustments, not much professionnal down there
        self.number_of_tile_width = self.screen_width // 100
        self.screen_height = self.master.winfo_screenheight() - 50
        self.number_of_tile_height = self.screen_height // 100

        self.general_padx = (self.screen_width / self.number_of_tile_width // 2 + 5)
        self.general_pady = (self.screen_height / self.number_of_tile_height // 2)

        self.tiles = dict()

        # Initialize the grid, fill it with tiles !!
        for c in range(0, self.number_of_tile_width):
            for r in range(1, self.number_of_tile_height):
                self.master.grid_rowconfigure(r, weight=1)
                # Create Labels to space all of it:
                tk.Label(master=self.master, pady=self.general_pady, padx=self.general_padx).grid(column=c, row=r)
                Tile(master=self.master).SetTile(row=r, column=c)  # see ? we can print simple time
            self.master.grid_columnconfigure(c, weight=1)  # auto ajust all the columns

        self.bind('<Visibility>', lambda
            evt: self.tab_update())  # bind the visibility event, if you clik on the tab to show it, you get the consequences

        self.update_inc = 0
        self.tick = ms
        self._tab_update()

    def _tab_update(self):
        if self.winfo_ismapped():
            self.tab_update()
        self.master.after(self.tick, self._tab_update)

    def tab_update(self):
        if self.winfo_ismapped():
            self.update_inc += 1

        if self.update_inc >= 5 * 60 * 1:  # 5 minutes
            pass
            # self.nb.select(0)
            # self.resert_timer

            # def resert_timer(self):
            # self.update_inc=0
            # print("reset")


class HotTab(Tab):
    """
    First Tab, which is the hottest from all of them
    Damn
    """

    def __init__(self, master=None, redis_db=None, nb=None):
        Tab.__init__(self, master=master, redis_db=redis_db, nb=nb)

        # Then create the tile you want !
        # the names here are crystal clear
        # first create it, second print it, boom

        self.tiles["Traffic_Dunkerque"] = Traffic_Duration_Tile(master=self.master, destination="Dunkerque",
                                                                redis_db=self.redis_db)
        self.tiles["Traffic_Dunkerque"].SetTile(row=1, column=0)
        self.tiles["Traffic_Seclin"] = Traffic_Duration_Tile(master=self.master, destination="Seclin",
                                                             redis_db=self.redis_db)
        self.tiles["Traffic_Seclin"].SetTile(row=2, column=0)
        self.tiles["Traffic_Valenciennes"] = Traffic_Duration_Tile(master=self.master, destination="Valenciennes",
                                                                   redis_db=self.redis_db)
        self.tiles["Traffic_Valenciennes"].SetTile(row=3, column=0)

        self.tiles["Weather"] = Weather_Tile(master=self.master, destination="Loos", redis_db=self.redis_db)
        self.tiles["Weather"].SetTile(row=1, column=13)

        self.tiles["Date"] = Time_Tile(master=self.master)
        self.tiles["Date"].SetTile(row=1, column=6, rowspan=2, columnspan=2)

        self.tiles["Infos"] = Local_Information_Tile(master=self.master, redis_db=self.redis_db)
        self.tiles["Infos"].SetTile(row=9, column=0)

        self.tiles["Traffic_Map"] = Traffic_Map_Tile(master=self.master)
        self.tiles["Traffic_Map"].SetTile(row=1, column=1, rowspan=4, columnspan=5)

        self.tiles["Gauge_IGP_Vehicule"] = GaugeTile(self.master, title="IGP_Vehicule")
        self.tiles["Gauge_IGP_Vehicule"].SetTile(row=4, column=13, columnspan=2)
        self.tiles["Gauge_IGP_Vehicule"].tag.set(gauge=75.0)

        self.tiles["Gauge_IGP_Locaux"] = Gauge_Tile(master=self.master, title="IGP_Locaux", redis_db=self.redis_db)
        self.tiles["Gauge_IGP_Locaux"].SetTile(row=4, column=15, columnspan=2)

        self.tiles["Gauge_Requipe"] = Gauge_Tile(master=self.master, title="Requipe",
                                                 redis_db=self.redis_db)
        self.tiles["Gauge_Requipe"].SetTile(row=5, column=13, columnspan=2)
        self.tiles["Gauge_VCS"] = Gauge_Tile(master=self.master, title="VCS", redis_db=self.redis_db)
        self.tiles["Gauge_VCS"].SetTile(row=5, column=15, columnspan=2)
        self.tiles["Gauge_VST"] = Gauge_Tile(master=self.master, title="VST", redis_db=self.redis_db)
        self.tiles["Gauge_VST"].SetTile(row=6, column=13, columnspan=2)
        self.tiles["Gauge_Secu"] = Gauge_Tile(master=self.master, title="Secu", redis_db=self.redis_db)
        self.tiles["Gauge_Secu"].SetTile(row=6, column=15, columnspan=2)

        self.tiles["Salle_TRAINNING"] = Salle_de_Reunion_Tile(master=self.master, salle="Salle_TRAINNING",
                                                              redis_db=self.redis_db)
        self.tiles["Salle_TRAINNING"].SetTile(row=5, column=0, columnspan=2)
        self.tiles["Salle_PROJECT"] = Salle_de_Reunion_Tile(master=self.master, salle="Salle_PROJECT",
                                                            redis_db=self.redis_db)
        self.tiles["Salle_PROJECT"].SetTile(row=5, column=2, columnspan=2)
        self.tiles["Salle_MEETING"] = Salle_de_Reunion_Tile(master=self.master, salle="Salle_MEETING",
                                                            redis_db=self.redis_db)
        self.tiles["Salle_MEETING"].SetTile(row=7, column=0, columnspan=2)
        self.tiles["Bureau_Passage_1"] = Salle_de_Reunion_Tile(master=self.master, salle="Bureau_Passage_1",
                                                               redis_db=self.redis_db)
        self.tiles["Bureau_Passage_1"].SetTile(row=6, column=0, columnspan=2)
        self.tiles["Bureau_Passage_2"] = Salle_de_Reunion_Tile(master=self.master, salle="Bureau_Passage_2",
                                                               redis_db=self.redis_db)
        self.tiles["Bureau_Passage_2"].SetTile(row=6, column=2, columnspan=2)

        self.tiles["Accident"] = Days_from_accident(master=self.master, redis_db=self.redis_db)
        self.tiles["Accident"].SetTile(row=1, column=8, columnspan=5, rowspan=2)

        self.tiles["Logo"] = Image_Tile(master=self.master)
        self.tiles["Logo"].SetTile(row=7, column=13, rowspan=2, columnspan=4)

        self.tiles["caroussel"] = Caroussel_Tile(master=self.master)
        self.tiles["caroussel"].SetTile(row=5, column=4, rowspan=4, columnspan=6)

        """
        self.tiles["test"] = funtile(master=self.master)
        self.tiles["test"].SetTile(row=8,column=0)
        """

        self.bind('<Visibility>', lambda evt: self.visibility_update())

        self.update_inc = 0

        self.tick = 200  # ms
        self.seconde = self.tick * 5
        self.minute = self.seconde * 60
        self.heure = self.minute * 60

    def visibility_update(self):
        self.tab_update()

    def tab_update(self):
        # some update stuff to do every 5 minutes
        # if current widget is mapped
        if self.winfo_ismapped():
            # every 5 min
            if (self.update_inc % (5 * 60 * 5)) == 0:
                print("5 min")
                if self.redis_db:
                    self.tiles["Traffic_Dunkerque"].update()
                    self.tiles["Traffic_Seclin"].update()
                    self.tiles["Traffic_Valenciennes"].update()

                    self.tiles["Weather"].update()
                    self.tiles["Infos"].getInformation()  # update the information from the base

                    self.tiles["Salle_TRAINNING"].update()
                    self.tiles["Salle_PROJECT"].update()
                    self.tiles["Salle_MEETING"].update()
                    self.tiles["Bureau_Passage_1"].update()
                    self.tiles["Bureau_Passage_2"].update()
                # wait for initial img loading
                self.master.after(500, self.tiles["Traffic_Map"].update)

            # every 20s
            if (self.update_inc % (5 * 20)) == 0:
                self.tiles["caroussel"].update() #WIP
                # update all defined tags
                Tags.update_tags()

            # every 0.2s
            if (self.update_inc % 1) == 0:
                self.tiles["Infos"].update()
                self.tiles["Date"].update()

                self.tiles["Gauge_IGP_Vehicule"].update()
                self.tiles["Gauge_IGP_Locaux"].update()
                self.tiles["Gauge_Requipe"].update()
                self.tiles["Gauge_VCS"].update()
                self.tiles["Gauge_VST"].update()
                self.tiles["Gauge_Secu"].update()

                self.tiles["Accident"].update()

        self.update_inc += 1


class ColdTab(Tab):
    def __init__(self, master=None, redis_db=None, nb=None, ms=2000):
        Tab.__init__(self, master=master, redis_db=redis_db, nb=nb, ms=ms)
        self.tiles["pdfs"] = list()
        self.bind('<Visibility>', lambda evt: self.tab_update())
        self.old = ""

    def tab_update(self):  # dynamique update of the pdf files in the cold page
        try:
            self.path = PDF_PATH
            os.chdir(self.path)
            current_pdf = glob.glob("*.pdf")

            print("scanning", self.old, current_pdf)

            if current_pdf != self.old:  # if there is any difference in the pdf list, REFRESH, else don't, there is no need
                print("TRULY DIFFERENT")
                for pdf in self.tiles["pdfs"]:
                    pdf.SetTile(remove=True)
                    pdf.destroy()
                self.tiles["pdfs"] = list()

                r = 1
                c = 1
                for file in current_pdf:
                    self.tiles["pdfs"].append(
                        Pdf_Tile(master=self.master, path=self.path, file=file, warplen=self.general_padx * 2 - 10))
                    self.tiles["pdfs"][-1].SetTile(row=r, column=c, columnspan=2, rowspan=2)
                    c = (c + 2)
                    if c >= self.number_of_tile_width - 1:
                        r = r + 2
                        c = 1
            else:
                print("same, nothing new")
            self.old = current_pdf
            print("saving", self.old, current_pdf)
            print("#" * 50)
        except:
            pass  # the directory "../pdf_reglementation/" isn't present


class Tile(tk.Frame):
    """
    Source of all the tile here
    Dafault : a gray, black bordered, case 
    """

    def __init__(self, master=None, pady=0, padx=0, bg=VERT, bd=ARDOISE, redis_db=None):
        tk.Frame.__init__(self, master=master, bg=bg, padx=padx, pady=pady,
                          highlightbackground=bd, highlightthickness=3, bd=0)
        self.master = master
        self.padx = padx
        self.pady = pady
        self.bg = bg
        self.bdcolor = bd
        self.redis_db = redis_db

    def SetTile(self, row="0", column="0", rowspan=1, columnspan=1, sticky=tk.N + tk.S + tk.E + tk.W, remove=None):
        # function to print a tile on the screen at the given coordonates
        if remove == False:
            self.grid(row=self.row, column=self.column, rowspan=self.rowspan, columnspan=self.columnspan,
                      sticky=self.sticky)
            self.grid_propagate(False)  # deny the resize of the frame
        elif remove == True:
            self.grid_remove()
        else:
            self.row = row
            self.column = column
            self.rowspan = rowspan
            self.columnspan = columnspan
            self.sticky = sticky
            self.configure(highlightbackground=self.bdcolor, highlightthickness=3, bd=0)

            self.grid(row=self.row, column=self.column, rowspan=self.rowspan, columnspan=self.columnspan,
                      sticky=self.sticky)
            self.grid_propagate(False)  # deny the resize of the frame

    def update(self):
        pass  # same as befor, no need to update anything right now


class Traffic_Duration_Tile(Tile):  # traffic duration #json
    def __init__(self, master=None, destination=None, redis_db=None):
        if destination:
            Tile.__init__(self, master=master, redis_db=redis_db)
            tk.LabelFrame.__init__(self, master=master, text="xxx :", background=self.cget("bg"))
            # self.grid()

            self.destination = destination
            self.configure(text=destination + " :", font=("bold"))
            self.grid()
            self.duration_frame = tk.Label(self, text="ForEver", anchor="e", background=self.cget("bg"),
                                           font=("bold"))
            self.duration_frame.grid(in_=self)
            if self.redis_db:
                self.duration = self.redis_db.get("Googlemap." + self.destination + ".duration").decode("utf-8")
            else:
                self.duration = "0 minutes"
            self.duration_minutes = self.time_str_to_int(self.duration)
            self.orange = int(self.duration_minutes * 1.2)
            self.red = int(self.duration_minutes * 1.4)

            self.normal_duration_label = tk.Label(self, text="Optimal :", background=self.cget("bg"))
            self.normal_duration_label.grid()
            self.normal_duration = tk.Label(self, text="ForEver", background=self.cget("bg"))
            self.normal_duration.grid()

        else:
            print(
                "Missing destination in the creation of the traffic tile\nSyntaxe : Traffic_Duration_Tile(destination=\"Ville\"\n")

    def time_str_to_int(self, time=""):
        # convert str("1 heure 10 minutes") into int(70) in a return variable
        result = time.split(" ")
        minutes = 0
        if len(result) == 4:  # if there is hour(s)
            minutes += int(result[0]) * 60
            minutes += int(result[2])

        if len(result) == 2:  # if here are only minutes
            minutes += int(result[0])
        return minutes

    def update(self):  # foreache self.Labels[destination][api url] bla bla bla
        """
        update function, call it 17 time each 5 minutes, from 07 AM to 06 PM ! 2500 calls is the limite
        """
        try:
            duration = self.redis_db.get("Googlemap." + self.destination + ".duration").decode("utf-8")
            self.normal_duration.configure(text=duration)
            # self.frame.configure(background=self.frame.cget("bg"))
            traffic_duration = self.redis_db.get("Googlemap." + self.destination + ".duration_traffic").decode("utf-8")
            traffic_duration_int = self.time_str_to_int(traffic_duration)

            if traffic_duration_int < self.orange:  # si le temps de trajet est entre la normale et +20% : VERT
                self.configure(bg="green")
                self.normal_duration_label.configure(bg="green")
                self.normal_duration.configure(bg="green")
            elif traffic_duration_int < self.red:  # si le temsp de trajet est entre +20% et +40% : ORANGE
                self.configure(bg="orange")
                self.normal_duration_label.configure(bg="orange")
                self.normal_duration.configure(bg="orange")
            else:  # si plus que 40 % : ROUGE !!!
                self.configure(bg="red")
                self.normal_duration_label.configure(bg="red")
                self.normal_duration.configure(bg="red")
            self.duration_frame.configure(text=traffic_duration, background=self.cget("bg"), font=("bold"))
        except Exception as e:
            print(e)
            self.duration_frame.configure(text="error updating")


class Weather_Tile(Tile):  # principal, she own all the day, could be divided if wanted #json
    def __init__(self, master=None, destination="Loos", redis_db=None):
        Tile.__init__(self, master=master, redis_db=redis_db, bg="gray")

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
            self.days.append(tk.LabelFrame(master=self, text="dd/mm/yyyy", bg="yellow",
                                           font=("bold", 10)))  # pour chaque jour on crée un LabelFrame avec la date
            self.dayslabel.append(tk.Label(master=self.days[c], text="empty", font=(
                'bold')))  # pour chaque labelframe on y ajoute un label pour les infos météo
            self.daysicone.append(tk.PhotoImage())  # on crée des images pour chaque jour
            self.daysiconelabel.append(tk.Label(master=self.days[c], image=self.daysicone[
                c],
                                                text="daily icone missing ?"))  # on met les images dans un label dans les label frame de chaque jour
            # end creation
            ## impression ##
            self.days[c].grid(row=2, column=c,
                              sticky="news")  # on imprime les jours a leur place (dernière ligne, chaque colonne)
            self.days[c].grid_propagate(False)  # on évite que les tuiles bougent

            self.dayslabel[c].grid(sticky="news")  # idem pour les infos météo de chaque jour
            self.dayslabel[c].grid_propagate(False)  # idem

            self.daysiconelabel[c].grid(sticky="news")  # on imprime les images
            # end impression
            # end other 4 days of the week

            ### Today ###
        self.todayframe = tk.LabelFrame(master=self, bg="red", text="Today :", font=("bold", 20))  # today title
        self.todaylabel = tk.Label(master=self.todayframe, text="empty", font=('courier', 18, 'bold'))  # today weather
        self.todayicone = tk.PhotoImage()  # today icone

        self.todayframe.grid(row=0, column=0, columnspan=4, rowspan=2, sticky="news")
        self.todayframe.grid_propagate(False)
        self.todaylabel.grid(column=0)
        self.todaylabel.grid_propagate(False)
        self.todayiconelabel = tk.Label(master=self.todayframe, image=self.todayicone, text="today icone missing ?",
                                        bg=self.todayframe.cget("bg"))
        self.todayiconelabel.grid(row=1)

    # end today

    def update(self):  # foreache self.Labels[destination][api url] bla bla bla
        """
        update function, 7200 call per day maximum
        """
        self.todayframe.configure(text=datetime.now().date())  # le labelframe du jour affiche la bonne date

        for i in range(4):
            self.days[i].configure(
                text=datetime.now().date() + timedelta(days=i + 1))  # chaque tuile des autres jours aussi

        try:  # on essaye de mettre a jour, problème récurant : réseau

            ###TODAY 
            # text of the Today cell
            today_mood = str(self.redis_db.get("Weather." + self.destination + ".Today.mood").decode("utf-8"))
            today_desc = str(self.redis_db.get("Weather." + self.destination + ".Today.description").decode("utf-8"))
            today_t = float(self.redis_db.get("Weather." + self.destination + ".Today.temp").decode("utf-8"))
            today_t_min = float(self.redis_db.get("Weather." + self.destination + ".Today.temp_min").decode("utf-8"))
            today_t_max = float(self.redis_db.get("Weather." + self.destination + ".Today.temp_max").decode("utf-8"))
            message = "Today's mood : %s\nDescription : %s\nTempérature actuelle : %.1f°C\n" + \
                      "            minimale : %.1f°C\n" + \
                      "            maximale : %.1f°C"
            message %= (today_mood, today_desc, today_t, today_t_min, today_t_max)
            self.todaylabel.configure(text=message, anchor=tk.W, justify=tk.LEFT)  # stiick the text to the left
            self.todayframe.configure(
                bg=self.weathercolor[self.redis_db.get("Weather." + self.destination + ".Today.mood").decode("utf-8")])
            self.todaylabel.configure(
                bg=self.todayframe.cget("bg"))  # to get the TodayFrame bg attribute, to use on the childer frame
            self.todayiconelabel.configure(bg=self.todayframe.cget("bg"))  # same as befor
            self.todayicone.configure(
                file=IMG_PATH + self.redis_db.get("Weather." + self.destination + ".Today.icon").decode(
                    "utf-8") + '.png')

            for inc in range(1, 5):  # other 4 days, same structure than befor, but simplier, less information needed
                day_mood = str(self.redis_db.get("Weather." + self.destination + ".Day" + str(inc) + ".mood").decode("utf-8"))
                day_t_min = int(float(self.redis_db.get("Weather." + self.destination + ".Day" + str(inc) + ".temp_min").decode("utf-8")))
                day_t_max = int(float(self.redis_db.get("Weather." + self.destination + ".Day" + str(inc) + ".temp_max").decode("utf-8")))
                message = "%s\nT mini %d°C\nT maxi %d°C"
                message %= (day_mood, day_t_min, day_t_max)
                self.dayslabel[inc - 1].configure(text=message)
                self.days[inc - 1].configure(bg=self.weathercolor[
                    self.redis_db.get("Weather." + self.destination + ".Day" + str(inc) + ".mood").decode("utf-8")])
                self.dayslabel[inc - 1].configure(bg=self.days[inc - 1].cget("bg"))
                self.daysicone[inc - 1].configure(file=IMG_PATH + self.redis_db.get(
                    "Weather." + self.destination + ".Day" + str(inc) + ".icon").decode("utf-8") + ".png")
                self.daysiconelabel[inc - 1].configure(bg=self.days[inc - 1].cget("bg"))
                inc += 1
        except Exception as e:
            print(e)
            self.days[0].configure(text="error 42")  # private joke, can be delete cause error never happend, humhum

    def SetTile(self, row="0", column="0", sticky=tk.N + tk.S + tk.E + tk.W, remove=False):
        self.row = row
        self.column = column
        self.rowspan = 3  # default, no need to change it's cool with  that configuration
        self.columnspan = 4  #
        self.sticky = sticky

        self.configure(highlightbackground=self.bdcolor, highlightthickness=3, bd=0)
        self.grid_propagate(False)

        if remove:
            self.grid_remove()
        else:
            self.grid(row=self.row, column=self.column, rowspan=self.rowspan, columnspan=self.columnspan,
                      sticky=self.sticky)
            self.grid_propagate(
                False)  # this disable the resizing effect of putting widget in the frame #sush a good boy


class Time_Tile(Tile):  # google map traffic # still need to define
    def __init__(self, master=None):
        Tile.__init__(self, master=master)
        self.day = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
        self.month = ["Janvier", "Fevrier", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre",
                      "Novembre", "Decembre"]

        for r in range(3):  # print it in the midle of a 3x3 grid !
            for c in range(3):
                self.grid_columnconfigure(c, weight=1)
                tk.Label(self, bg=self.cget("bg")).grid(row=r, column=c)
            self.grid_rowconfigure(r, weight=1)

        self.clock = tk.Label(self, font=('digital-7', 30), bg=self.cget("bg"), fg='green')
        self.clock.grid(row=1, column=1)
        self.Day = tk.Label(self, bg=self.cget("bg"), text=self.day[datetime.today().weekday()], anchor=tk.W,
                            justify=tk.LEFT, font=('bold', 15))
        self.Day.grid(row=0, column=0, columnspan=3, sticky="news")

        self.time = ""

    def update(self):
        # 200 ms of refresh, don't put a lot of work here
        tmp = str(datetime.today().date())[
              :10]  # yyyy-mm-dd => dd-mm-yyyy #following 2 lines are about choice in last comment of each
        # jour=self.day[datetime.today().weekday()] + " " + tmp[-2:] + "-" + self.month[int(tmp[-5:-3])] + "-" + tmp[0:4] #Jeudi 19 Mai 2018
        jour = self.day[datetime.today().weekday()] + " " + tmp[-2:] + "-" + tmp[-5:-3] + "-" + tmp[
                                                                                                0:4]  # Jeudi 19-04-2018
        self.Day.configure(text=jour)
        heure = str(datetime.now().time())[:8]
        self.clock.configure(text=heure)


class Traffic_Map_Tile(Tile):  # google map traffic # still need to define
    def __init__(self, master=None, file="/media/ramdisk/Traffic_Map.png"):
        Tile.__init__(self, master=master)
        self.file = file
        self.image = tk.PhotoImage()
        # self.image = self.image.zoom(2).subsample(3) #resize the image, always zoom befor subsample , so no pixel are lost
        self.labelimage = tk.Label(self, image=self.image, text="Google map traffic image missing ?")
        self.labelimage.grid()

    def update(self):
        try:
            self.image.configure(file=self.file)
        except:
            pass
        # self.image = self.image.zoom(2).subsample(3)
        self.labelimage.configure(image=self.image)


class Local_Information_Tile(Tile):  # 1 * x "header" or "footer" #still need to define
    def __init__(self, master=None, redis_db=None):
        Tile.__init__(self, master=master, redis_db=redis_db)
        # width --> width in chars, height --> lines of text
        self.text_width = 44  # number of space to fill the all text area, user friendlier
        self.text = tk.Label(self, height=1, bg='yellow', )
        self.columnconfigure(0, weight=1)  # to take all the weight of the bottom screen
        self.text.grid(row=0, column=0, sticky="news")
        # use a proportional font to handle spaces correctly
        self.text.config(font=('courier', 48, 'bold'))
        self.s = ""
        self.k = 0  # inc which will count the number of char show, so the number of char to shown

    def update(self):
        # update the text on the screen
        if self.k >= (len(self.s) - (self.text_width // 2)):
            self.k = 0
        # use string slicing to do the trick
        self.ticker_text = self.s[self.k:self.k + self.text_width]  # the "k"ey of the trick ....
        # print (self.ticker_text)#test
        self.text.configure(text=self.ticker_text)
        self.k += 1

    def getInformation(self):
        try:
            self.s = self.redis_db.get("Info").decode("utf-8")
        except:
            self.s = " " * self.text_width + "error redis" + " " * self.text_width

    def SetTile(self, row="0", column="0", sticky=tk.N + tk.S + tk.E + tk.W, remove=False):
        # can't we use the Tile.SetFrame(...) ? let's test it later #WIP
        self.row = row
        self.column = column
        self.rowspan = 1
        self.columnspan = 17
        self.sticky = sticky

        self.configure(highlightbackground=self.bdcolor, highlightthickness=3, bd=0)
        self.grid_propagate(False)

        if remove:
            self.grid_remove()
        else:
            self.grid(row=self.row, column=self.column, rowspan=self.rowspan, columnspan=self.columnspan,
                      sticky=self.sticky)
            self.grid_propagate(
                False)  # this disable the resizing effect of putting widget in the frame #sush a good boy


class Flyspray_Tile(Tile):  # still need to define
    def __init__(self):
        pass


class Pdf_Tile(Tile):  # clickable pdf luncher
    def __init__(self, master=None, path=PDF_PATH, file="", warplen=100):
        Tile.__init__(self, master=master)
        self.path = path
        self.file = file
        self.warplen = warplen
        self.name = tk.Label(self, text=self.file, wraplength=200, bg=self.cget("bg"),
                             font=("courrier", 20, "bold"))
        self.name.grid()
        self.bind("<Button-1>", self.clicked)
        self.name.bind("<Button-1>", self.clicked)

    def clicked(self, event):
        try:
            subprocess.call(["/usr/bin/xpdf", self.path + self.file])
        except:
            pass

    def SetTile(self, row="0", column="0", rowspan=1, columnspan=1, sticky=tk.N + tk.S + tk.E + tk.W, remove=False):
        # function to print a tile on the screen at the given coordonates
        self.row = row
        self.column = column
        self.rowspan = rowspan
        self.columnspan = columnspan
        self.sticky = sticky
        self.configure(bg=self.cget("bg"), highlightbackground=FUSHIA, highlightthickness=3, bd=0)

        # self.frame.configure(highlightbackground=self.bdcolor, highlightthickness=3, bd=0) #this is used to have a border of "3" pixel

        if remove:
            self.grid_remove()
        else:
            self.grid(row=self.row, column=self.column, rowspan=self.rowspan, columnspan=self.columnspan,
                      sticky=self.sticky)
            self.grid_propagate(
                False)  # this disable the resizing effect of putting widget in the frame #sush a good boy


class Salle_de_Reunion_Tile(Tile):  # dummy #json # need more information
    def __init__(self, master=None, redis_db=None, salle="Ceilling"):
        Tile.__init__(self, master=master, redis_db=redis_db)
        self.salle_name = salle
        for r in range(3):  # print it in the midle of a 3x3 grid !
            for c in range(3):
                self.grid_columnconfigure(c, weight=1)
                tk.Label(self, bg=self.cget("bg")).grid(row=r, column=c)
            self.grid_rowconfigure(r, weight=1)

        self.salle = tk.Label(self, text=self.salle_name, bg=self.cget("bg"))
        self.salle.grid(row=1, column=0)
        self.status = "Unocc"
        self.salle_status = tk.Label(self, text="UnOccuped", bg=self.cget("bg"))
        self.salle_status.grid(row=2, column=0)

        try:
            self.image_Orange = tk.PhotoImage(file=IMG_PATH + "TraficLight_Orange.png").subsample(10)
            self.image_Green = tk.PhotoImage(file=IMG_PATH + "TraficLight_Green.png").subsample(10)
            self.image_Red = tk.PhotoImage(file=IMG_PATH + "TraficLight_Red.png").subsample(10)
        except:
            self.image_Orange = tk.PhotoImage()
            self.image_Green = tk.PhotoImage()
            self.image_Red = tk.PhotoImage()

        self.image = tk.Label(self, image=self.image_Orange, bg=self.cget("bg"))
        self.image.grid(row=0, column=2, rowspan=3)

    def update(self):
        old = self.status
        self.status = self.redis_db.get("Widget_salle." + self.salle_name).decode("utf-8")
        if old != self.status:
            print(datetime.now(), self.salle_name, old, " => ", self.status)

        self.salle_status.configure(text=self.status)
        print(self.status)
        if self.status == "Occ" or self.status == "OccPeriod":
            self.image.configure(image=self.image_Red)
        elif self.status == "Unocc":
            self.image.configure(image=self.image_Orange)
        elif self.status == "UnoccRepeat":
            self.image.configure(image=self.image_Green)
        else:
            print("wrong status :", self.status)


class Gauge_Tile(Tile):  # compteur aiguille
    def __init__(self, master=None, title="Nathemoment", redis_db=None):
        Tile.__init__(self, master=master, redis_db=redis_db)
        self.meter = 0
        self.angle = 0
        self.var = tk.IntVar(self, 0)
        self.title = title
        self.label = tk.Label(self, text=self.title.replace("_", " "), font="bold")
        self.label.grid(sticky="news")

        self.gauge = tk.Canvas(self, width=220, height=110, borderwidth=2, relief='sunken', bg='white')
        self.gauge.grid()

        self.meter = self.gauge.create_line(100, 100, 10, 100, fill='grey', width=3, arrow='last')
        self.angle = 0
        self.gauge.lower(self.meter)
        self.updateMeterLine(0.2)

        self.gauge.create_arc(20, 10, 200, 200, extent=108, start=36, style='arc', outline='black')

        # self.var.trace_add('write', self.updateMeter)  # if this line raises an error, change it to the old way of adding a trace: self.var.trace('w', self.updateMeter)
        self.var.trace('w', self.updateMeter)

    def updateMeterLine(self, a):
        oldangle = self.angle
        self.angle = a
        x = 112 - 90 * math.cos(a * math.pi)
        y = 100 - 90 * math.sin(a * math.pi)
        self.gauge.coords(self.meter, 112, 100, x, y)

    def updateMeter(self, name1, name2, op):
        # Convert variable to angle on trace
        mini = 0
        maxi = 100
        pos = (self.var.get() - mini) / (maxi - mini)
        self.updateMeterLine(pos * 0.6 + 0.2)

    def update(self, inc=0):
        # bla bla bla inc = self.redis_db.get("blablabla").decode("utf-8")
        if self.redis_db:
            try:
                inc = int(self.redis_db.get("Gauges." + self.title + ".current").decode("utf-8"))
                inc = (100 * inc) / int(self.redis_db.get("Gauges." + self.title + ".goal").decode("utf-8"))
                try:  # WIP
                    current = self.redis_db.get("Gauges." + self.title + ".current").decode("utf-8")
                    total = self.redis_db.get("Gauges." + self.title + ".goal").decode("utf-8")
                    self.label.configure(text=self.title.replace("_", " ") + ":" + str(current) + "/" + str(total))
                except Exception as e:
                    pass
                    #print(self.title, "1", e)
            except Exception as e:
                #print(self.title, "2", e)
                inc = 50
        else:
            inc = 0

        if inc < 50:
            self.gauge.configure(bg="red")
        elif inc < 75:
            self.gauge.configure(bg="orange")
        else:
            self.gauge.configure(
                bg="green")  # else if  > 100% ? dunno but it can happend if they are ealier than expected
        self.var.set(inc)


# alternative compteur aiguille
class GaugeTile(Tile):
    GAUGE_MIN = 0.0
    GAUGE_MAX = 100.0

    def __init__(self, master, title, tag=GaugeTag()):
        Tile.__init__(self, master=master)
        # public
        self.title = title
        self.tag = tag
        # tk build
        self.label = tk.Label(self, text=self.title.replace('_', ' '), font='bold')
        self.label.grid(sticky='news')
        self.can = tk.Canvas(self, width=220, height=110, borderwidth=2, relief='sunken', bg='white')
        self.can.grid()
        self.can_arrow = self.can.create_line(100, 100, 10, 100, fill='grey', width=3, arrow='last')
        self.can.lower(self.can_arrow)
        self.can.create_arc(20, 10, 200, 200, extent=108, start=36, style='arc', outline='black')
        # subscribe to tag update
        self.tag.subscribe(self._on_tag_update)

    def _on_tag_update(self, tag):
        # check tag value
        try:
            var_percent = float(self.tag.gauge)
        except TypeError:
            var_percent = float('nan')
        # update widget
        if not math.isnan(var_percent):
            # convert value
            ratio = (var_percent - self.GAUGE_MIN) / (self.GAUGE_MAX - self.GAUGE_MIN)
            # set arrow on widget
            self._set_arrow(ratio)
            # update alarm, warn, fine status
            if ratio < 0.5:
                self.can.configure(bg='red')
            elif ratio < 0.75:
                self.can.configure(bg='orange')
            else:
                self.can.configure(bg='green')
            self.label.configure(text=self.title)
        else:
            self._set_arrow(0.0)
            self.can.configure(bg='white')
            self.label.configure(text=self.title + ' (N/A)')

    def _set_title(self):
        self.label.configure(text=self.title)

    def _set_arrow(self, ratio):
        # normalize ratio : 0.2 to 0.8
        ratio = ratio * 0.6 + 0.2
        # compute arrow head
        x = 112 - 90 * math.cos(ratio * math.pi)
        y = 100 - 90 * math.sin(ratio * math.pi)
        # update canvas
        self.can.coords(self.can_arrow, 112, 100, x, y)


class Days_from_accident(Tile):  # WIP
    def __init__(self, master=None, redis_db=None):
        Tile.__init__(self, master=master, redis_db=redis_db)
        tk.LabelFrame.__init__(self, master=master, text="Safety is number one priority !",
                               font=('courier', 18, 'bold'),
                               bg="white")

        for c in range(5):
            for r in range(3):
                self.grid_rowconfigure(r, weight=1)
                if c > 0:
                    tk.Label(self, bg="white").grid(row=r, column=c, )
            self.columnconfigure(c, weight=1)

        self.nbjour = tk.Label(self, text="Null", font=('courier', 24, 'bold'), fg=FUSHIA, bg=self.cget("bg"))
        self.nbjour.grid(row=1, column=0, columnspan=2)

        tk.Label(self, text="Jours sans accident",
                 font=('courier', 20, 'bold'), bg=self.cget("bg")).grid(row=1, column=2, columnspan=3)

    def update(self):
        # update datetime timedelta until today an the accident day
        tmp_now = datetime.now()
        try:
            tmp = self.redis_db.get("Accident_day").decode("utf-8").split(":")  # format dd:mm:yyyy
        except:
            tmp = "1:1:2008".split(":")
        day = int(tmp[0])
        month = int(tmp[1])
        year = int(tmp[2])
        tmp_accident = datetime(year, month, day)

        tmp_difference = tmp_now - tmp_accident

        self.nbjour.configure(text=str(tmp_difference.days))


class Image_Tile(Tile):
    def __init__(self, master=None, file=IMG_PATH + "logo.png"):
        Tile.__init__(self, master=master)
        self.file = file
        try:
            self.image = tk.PhotoImage(file=self.file).subsample(4)
        except:
            self.image = tk.PhotoImage()

        self.labelimage = tk.Label(self, image=self.image, bg="#FFFFFF")
        self.labelimage.grid()


class Caroussel_Tile(Tile):
    def __init__(self, master=None):
        Tile.__init__(self, master=master, bg="white")
        # private
        self._img_index = 0
        self._img_files = list()
        # tk job
        self.tk_img = tk.PhotoImage()
        self.lbl_img = tk.Label(self, image=self.tk_img)
        self.lbl_img.grid(sticky=tk.NSEW)
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
            logging.debug('load img "%s"' % self._img_files[self._img_index])
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
    root = tk.Tk()
    root.attributes('-fullscreen', True)
    app = Application(master=root)
    app.mainloop()

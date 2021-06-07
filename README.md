# tk-dashboard

### Raspberry Pi setup

```bash
# HMI package dependency
sudo apt update && sudo apt -y dist-upgrade
sudo apt install -y supervisor xpdf imagemagick python3-cairocffi xscreensaver
# security setup
sudo apt install -y fail2ban ufw
sudo ufw allow proto tcp from 192.168.0.0/24 to any port ssh
sudo ufw allow proto tcp from 192.168.0.0/24 to any port 6379
sudo ufw enable
# add project space on rpi host
sudo mkdir -p /srv/dashboard/
# install docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
rm get-docker.sh
# use docker cli with pi user
sudo usermod -aG docker pi
sudo reboot
```

### Docker setup

```bash
cd docker
# start the master dashboard stack
./master-setup.sh
# start the slave dashboard stack
./slave-setup.sh
```

### Turn off screensaver

In LXDE GUI menu go to Preferences option/screensaver and deactivate it.

### Add shortcut to Desktop

```bash
cp home/pi/Desktop/* /home/pi/Desktop/
```

### Setup supervisor

```bash
# Loos dashboard
sudo cp -r scripts/loos/* /usr/local/bin/
# Messein dashboard
sudo cp -r scripts/messein/* /usr/local/bin/
# for loos master dashboard (do all external requests and own the redis db)
sudo cp etc/supervisor/conf.d/dashboard_master_loos.conf /etc/supervisor/conf.d/
# for loos slave dashboard (connect to master redis db and sync all files with master)
sudo cp etc/supervisor/conf.d/dashboard_slave_loos.conf /etc/supervisor/conf.d/
# for messein master dashboard (do all external requests and own the redis db)
sudo cp etc/supervisor/conf.d/dashboard_master_messein.conf /etc/supervisor/conf.d/
# for messein slave dashboard (connect to master redis db and sync all files with master)
sudo cp etc/supervisor/conf.d/dashboard_slave_messein.conf /etc/supervisor/conf.d/
# reload conf
sudo supervisorctl update
```

### Setup remote access

```bash
sudo apt-get install -y x11vnc
# create password
x11vnc -storepasswd
# launch server as you want
x11vnc -usepw -forever &
```

### Setup for auto sync files (multi-screen case)

```bash
# create ssh key and copy it to central dashboard (file src at 192.168.0.60)
ssh-keygen
ssh-copy-id pi@192.168.0.60
# now we can manually sync file
rsync -aALxXv --delete 192.168.0.60:/srv/dashboard/hmi/. /srv/dashboard/hmi/.
# see scripts/dashboard_sync_files.py to automate this
```

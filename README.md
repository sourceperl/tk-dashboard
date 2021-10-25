# tk-dashboard

### Raspberry Pi setup

```bash
# HMI package dependency
sudo apt update && sudo apt -y dist-upgrade
sudo apt install -y supervisor xpdf imagemagick xscreensaver fonts-freefont-ttf \
                    python3-cairocffi python3-pil python3-pil.imagetk
sudo pip3 install redis==3.5.3
# security setup
sudo apt install -y fail2ban ufw
# add project space on rpi host
sudo mkdir -p /srv/dashboard/
sudo mkdir -p /opt/tk-dashboard/bin/
sudo mkdir -p /etc/opt/tk-dashboard/
# install docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
rm get-docker.sh
# install docker-compose
sudo pip3 install docker-compose
# use docker cli with pi user
sudo usermod -aG docker pi
sudo reboot
```

### Network setup

```bash
# UFW firewall setup
sudo ufw allow proto tcp from 192.168.0.0/24 to any port ssh
sudo ufw enable
```

WARN: Docker daemon overide UFW rules (since it directly write on iptables). So, to filter container traffic, we need to add custom iptables rules via the aptly named "DOCKER-USER" chain. Here, we done this with custom add-ons to /etc/ufw/after.rules for IPv4 and /etc/ufw/after6.rules for IPv6. This files are load at every ufw reload (for sure, at startup too).

more at  https://docs.docker.com/network/iptables/

```bash
# append DOCKER-USER rules to /etc/ufw/after.rules (IPv4)
# ensure new line after "COMMIT"
sudo sh -c 'echo "" >> /etc/ufw/after.rules'
sudo sh -c 'cat ufw/after.rules.add >> /etc/ufw/after.rules'
sudo sh -c 'echo "" >> /etc/ufw/after.rules'
```

```bash
# append DOCKER-USER rules to /etc/ufw/after6.rules (IPv6)
# ensure new line after "COMMIT"
sudo sh -c 'echo "" >> /etc/ufw/after6.rules'
sudo sh -c 'cat ufw/after6.rules.add >> /etc/ufw/after6.rules'
sudo sh -c 'echo "" >> /etc/ufw/after6.rules'
```

```bash
# ufw reload to take care of after rules files
sudo ufw reload
```

### Add a configuration file

```bash
# start from example
cp conf/example/dashboard.conf /etc/opt/tk-dashboard/
# customize it
vim /etc/opt/tk-dashboard/dashboard.conf
```

### Setup for slave (add ssh key to allow redis relay and files sync)

```bash
# create ssh key and copy it to central dashboard (file src at 192.168.0.60)
ssh-keygen
ssh-copy-id pi@192.168.0.60
# now we can manually sync file
rsync -aALxXv --delete 192.168.0.60:/srv/dashboard/hmi/. /srv/dashboard/hmi/.
# see scripts/dashboard_sync_files.py to automate this
```

### Docker setup

#### On all dashboard

```bash
cd docker
./docker-setup.sh
```

#### Loos

```bash
# Loos setup
cd loos/
# start the master dashboard stack
./master-setup.sh
# start the slave dashboard stack
# ensure ssh-copy-id is set to avoid ip ban by fail2ban
./slave-setup.sh
```

#### Messein

```bash
# Messein setup
cd messein/
# start the master dashboard stack
./master-setup.sh
# start the slave dashboard stack
# ensure ssh-copy-id is set to avoid ip ban by fail2ban
./slave-setup.sh
```

### Setup supervisor

#### On all dashboard

```bash
sudo cp -r scripts/common/* /opt/tk-dashboard/bin/
```

#### Loos

```bash
sudo cp -r scripts/loos/* /opt/tk-dashboard/bin/
# for loos master dashboard
sudo cp supervisor/dashboard_master_loos.conf /etc/supervisor/conf.d/
# for loos slave dashboard
sudo cp supervisor/dashboard_slave_loos.conf /etc/supervisor/conf.d/
# reload conf
sudo supervisorctl update
```

#### Messein

```bash
sudo cp -r scripts/messein/* /opt/tk-dashboard/bin/
# for messein master dashboard
sudo cp supervisor/dashboard_master_messein.conf /etc/supervisor/conf.d/
# for messein slave dashboard
sudo cp supervisor/dashboard_slave_messein.conf /etc/supervisor/conf.d/
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

### Turn off screensaver

In LXDE GUI menu go to Preferences option/screensaver and deactivate it.

### Add shortcut to Desktop

```bash
cp home/pi/Desktop/* /home/pi/Desktop/
```

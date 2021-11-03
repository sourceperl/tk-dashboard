# tk-dashboard

### Raspberry Pi setup

```bash
# HMI package dependency
sudo apt update && sudo apt -y dist-upgrade
sudo apt install -y supervisor xpdf imagemagick xscreensaver fonts-freefont-ttf \
                    python3-cairocffi python3-pil python3-pil.imagetk fail2ban ufw
sudo pip3 install redis==3.5.3

# add project space on rpi host
sudo mkdir -p /srv/dashboard/
sudo mkdir -p /opt/tk-dashboard/bin/
sudo mkdir -p /etc/opt/tk-dashboard/
```

```bash
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

### Add configuration files

HMI and import/export process configuration

```bash
# start from example
sudo cp conf/example/dashboard.conf /etc/opt/tk-dashboard/
# customize it
sudo vim /etc/opt/tk-dashboard/dashboard.conf
```

Redis configuration for master

```bash
sudo cp redis/redis-master.conf /etc/opt/tk-dashboard/
```

Redis configuration for slave

```bash
sudo cp redis/redis-slave.conf /etc/opt/tk-dashboard/
```

**Update default passwords 'pwd' with custom one.**

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

#### Loos master

```bash
cd docker/
./docker-setup.sh
./loos-master-setup.sh
```

#### Loos slave

***Ensure ssh-copy-id is set to avoid ip ban by fail2ban.***

```bash
cd docker/
./docker-setup.sh
./loos-slave-setup.sh
```

#### Messein master

```bash
cd docker/
./docker-setup.sh
./messein-master-setup.sh
```

#### Messein slave

***Ensure ssh-copy-id is set to avoid ip ban by fail2ban.***

```bash
cd docker/
./docker-setup.sh
./messein-slave-setup.sh
```


### Setup supervisor

#### Loos master

```bash
# scripts copy
sudo cp scripts/board-hmi-loos.py /opt/tk-dashboard/bin/
# supervisor setup
sudo cp supervisor/dashboard_master_loos.conf /etc/supervisor/conf.d/
sudo supervisorctl update
```

#### Loos slave

```bash
# scripts copy
sudo cp scripts/board-hmi-loos.py /opt/tk-dashboard/bin/
sudo cp scripts/board-sync-files.py /opt/tk-dashboard/bin/
# supervisor setup
sudo cp supervisor/dashboard_slave_loos.conf /etc/supervisor/conf.d/
sudo supervisorctl update
```

#### Messein master

```bash
# scripts copy
sudo cp scripts/board-hmi-messein.py /opt/tk-dashboard/bin/
# supervisor setup
sudo cp supervisor/dashboard_master_messein.conf /etc/supervisor/conf.d/
sudo supervisorctl update
```

#### Messein slave

```bash
# scripts copy
sudo cp scripts/board-hmi-messein.py /opt/tk-dashboard/bin/
sudo cp scripts/board-sync-files.py /opt/tk-dashboard/bin/
# supervisor setup
sudo cp supervisor/dashboard_slave_messein.conf /etc/supervisor/conf.d/
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

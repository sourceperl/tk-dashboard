# tk-dashboard

## Host setup

```bash
# HMI package dependency
sudo apt update && sudo apt -y dist-upgrade
sudo apt install -y supervisor xpdf imagemagick xscreensaver fonts-freefont-ttf \
                    python3-cairocffi python3-pil python3-pil.imagetk \
                    fail2ban ufw openssl vim nmap
sudo pip3 install redis==3.5.3

# add project space on rpi host
sudo mkdir -p /opt/tk-dashboard/bin/
sudo mkdir -p /etc/opt/tk-dashboard/redis/
sudo mkdir -p /etc/opt/tk-dashboard/stunnel/certs/
```

## Add docker

```bash
# install docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
rm get-docker.sh

# install docker-compose
sudo pip3 install docker-compose

# use docker cli with pi user
sudo usermod -aG docker pi

# for Raspberry Pi as docker host
# enable cgroup: add "cgroup_enable=memory cgroup_memory=1" to kernel args
sudo sed -i '/cgroup_enable=memory/!s/$/ cgroup_enable=memory/' /boot/cmdline.txt
sudo sed -i '/cgroup_memory=1/!s/$/ cgroup_memory=1/' /boot/cmdline.txt
# exclude docker virtual interfaces from dhcpcd
# this avoid dhcpcd service crashes (see https://github.com/raspberrypi/linux/issues/4092/)
sudo sh -c 'echo "" >> /etc/dhcpcd.conf'
sudo sh -c 'echo "# exclude docker virtual interfaces" >> /etc/dhcpcd.conf'
sudo sh -c 'echo "denyinterfaces veth*" >> /etc/dhcpcd.conf'

sudo reboot
```

## Network setup

### Firewall

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

### Setup an SSL tunnel for redis slaves sync and Loos redis share

#### Loos master

Create cert/key for Loos master server

```bash
# create private key and self-signed certificate for server
target_prefix=/etc/opt/tk-dashboard/stunnel/certs/redis-loos-m-srv
sudo openssl req -x509 -newkey rsa:4096 -days 3650 -nodes \
                 -subj "/C=FR/ST=Haut-de-France/L=Loos/CN=dashboard-loos-master-srv" \
                 -keyout ${target_prefix}.key \
                 -out ${target_prefix}.crt
```

Stunnel server setup

```bash
# add configuration file to tk-dashboard conf
sudo cp stunnel/redis-loos-m-tls-srv.conf /etc/opt/tk-dashboard/stunnel/
# add directory for trusted certs of clients (local slave or remote share cli)
sudo mkdir -p /etc/opt/tk-dashboard/stunnel/certs/trusted.d/
# copy trusted client certificate to trusted.d directory (see below)
sudo cp redis-loos-s-cli-to-master.crt /etc/opt/tk-dashboard/stunnel/certs/trusted.d/
sudo cp redis-messein-m-cli-to-loos.crt /etc/opt/tk-dashboard/stunnel/certs/trusted.d/
# add symbolic links to certs hash values (need by stunnel CApath)
sudo c_rehash /etc/opt/tk-dashboard/stunnel/certs/trusted.d/
```

#### Loos slave

Create cert/key for Loos slave client

```bash
# create private key and self-signed certificate for server
target_prefix=/etc/opt/tk-dashboard/stunnel/certs/redis-loos-s-cli-to-master
sudo openssl req -x509 -newkey rsa:4096 -days 3650 -nodes \
                 -subj "/C=FR/ST=Haut-de-France/L=Loos/CN=dashboard-loos-slave-cli" \
                 -keyout ${target_prefix}.key \
                 -out ${target_prefix}.crt
```

Stunnel Loos slave client setup

```bash
# add configuration file to tk-dashboard conf
sudo cp stunnel/redis-loos-s-tls-cli-to-master.conf /etc/opt/tk-dashboard/stunnel/
```

#### Messein master

Create cert/key for Messein master server

```bash
# create private key and self-signed certificate for server
target_prefix=/etc/opt/tk-dashboard/stunnel/certs/redis-messein-m-srv
sudo openssl req -x509 -newkey rsa:4096 -days 3650 -nodes \
                 -subj "/C=FR/ST=Grand Est/L=Messein/CN=dashboard-messein-master-srv" \
                 -keyout ${target_prefix}.key \
                 -out ${target_prefix}.crt
```

Create cert/key for Messein master client to Loos redis db

```bash
# create private key and self-signed certificate for server
target_prefix=/etc/opt/tk-dashboard/stunnel/certs/redis-messein-m-cli-to-loos
sudo openssl req -x509 -newkey rsa:4096 -days 3650 -nodes \
                 -subj "/C=FR/ST=Grand Est/L=Messein/CN=dashboard-messein-master-cli" \
                 -keyout ${target_prefix}.key \
                 -out ${target_prefix}.crt
```

Stunnel server setup (only on Messein master dashboard)

```bash
# add configuration file to tk-dashboard conf
sudo cp stunnel/redis-messein-m-tls-srv.conf /etc/opt/tk-dashboard/stunnel/
sudo cp stunnel/redis-messein-m-tls-cli-to-loos.conf /etc/opt/tk-dashboard/stunnel/
# add directory for trusted certs of clients
sudo mkdir -p /etc/opt/tk-dashboard/stunnel/certs/trusted.d/
# copy server certificate to certs directory (copy it from server host)
sudo cp redis-loos-m-srv.crt /etc/opt/tk-dashboard/stunnel/certs/
# copy trusted client certificate to trusted.d directory (see below)
sudo cp redis-messein-s-cli-to-master.crt /etc/opt/tk-dashboard/stunnel/certs/trusted.d/
# add symbolic links to certs hash values (need by stunnel CApath)
sudo c_rehash /etc/opt/tk-dashboard/stunnel/certs/trusted.d/
```

#### Messein slave

Create cert/key for Messein slave client

```bash
# create private key and self-signed certificate for client
target_prefix=/etc/opt/tk-dashboard/stunnel/certs/redis-messein-s-cli-to-master
sudo openssl req -x509 -newkey rsa:4096 -days 3650 -nodes \
                 -subj "/C=FR/ST=Grand Est/L=Messein/CN=dashboard-messein-slave-cli" \
                 -keyout ${target_prefix}.key \
                 -out ${target_prefix}.crt
```
Stunnel Messein slave client setup

```bash
# add configuration file to tk-dashboard conf
sudo cp stunnel/redis-messein-s-tls-cli-to-master.conf /etc/opt/tk-dashboard/stunnel/
# copy server certificate to certs directory (copy it from server host)
sudo cp redis-loos-m-srv.crt /etc/opt/tk-dashboard/stunnel/certs/
```

## Add configuration files

HMI and import/export process configuration

```bash
# start from examples
# redis admin conf (readable only by root)
sudo cp board/board-admin.conf /etc/opt/tk-dashboard/board-admin.conf
sudo chmod 600 /etc/opt/tk-dashboard/board-admin.conf
# board conf
sudo cp board/loos-example.board.conf /etc/opt/tk-dashboard/board.conf
# or
sudo cp board/messein-example.board.conf /etc/opt/tk-dashboard/board.conf
# customize it
sudo vim /etc/opt/tk-dashboard/board.conf
```

Redis configuration for master

```bash
sudo cp redis/redis-master.conf /etc/opt/tk-dashboard/redis/
```

Redis configuration for slave

```bash
sudo cp redis/redis-slave.conf /etc/opt/tk-dashboard/redis/
```

**Update default passwords 'pwd' with custom one or better with sha256 hash.
The tool "redis_pass_gen.py" in utils/ can be useful for this task.
Don't forget to update "board-admin.conf" to reflect it's changes.**

## Docker setup

### Loos master

```bash
cd docker/
./docker-setup.sh
./loos-master-compose up -d
```

### Loos slave

```bash
cd docker/
./docker-setup.sh
./loos-slave-compose up -d
```

### Messein master

```bash
cd docker/
./docker-setup.sh
./messein-master-compose up -d
```

### Messein slave

```bash
cd docker/
./docker-setup.sh
./messein-slave-compose up -d
```

### Init for all master


```bash
docker exec board-admin-shell board-init-static
```

## Setup supervisor

### Loos HMI master and slave

```bash
# scripts copy
sudo cp scripts/board-hmi-loos.py /opt/tk-dashboard/bin/
# supervisor setup
sudo cp supervisor/dashboard_loos.conf /etc/supervisor/conf.d/
sudo supervisorctl update
```

### Messein HMI master and slave

```bash
# scripts copy
sudo cp scripts/board-hmi-messein.py /opt/tk-dashboard/bin/
# supervisor setup
sudo cp supervisor/dashboard_messein.conf /etc/supervisor/conf.d/
sudo supervisorctl update
```

## Setup remote access

```bash
sudo apt-get install -y x11vnc
# create password
x11vnc -storepasswd
# launch server as you want
x11vnc -usepw -forever &
```

## Turn off screensaver

In LXDE GUI menu go to Preferences option/screensaver and deactivate it.

## Add shortcut to Desktop

```bash
cp home/pi/Desktop/* /home/pi/Desktop/
```

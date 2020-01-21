# tk-dashboard

### Create RAM disk space

    # create a 16M RAM disk (file system in RAM: tmpfs) in /media/ramdisk/
    sudo mkdir -p /media/ramdisk/
    # add line for mount RAMDISK at system startup if not already exist
    LINE='tmpfs           /media/ramdisk  tmpfs   defaults,size=16M 0       0'
    FILE='/etc/fstab'
    sudo grep -q "$LINE" "$FILE" || echo "$LINE" | sudo tee -a "$FILE"
    # reboot to take effect
    sudo reboot

### Setup redis

    sudo apt-get install redis-server
    # edit config file /etc/redis/redis.conf
    # for use with pi SD card, we need to reduce backup cycle
    # -> here we use only "save 3600 1"

### Copy config file (URL, API credentials, misc...)

    # edit home/pi/.dashboard_config_sample with credentials
    # save as .dashboard_config
    cp home/pi/.dashboard_config /home/pi/

### Setup

    sudo pip3 install -r requirements.txt
    sudo cp -r scripts/* /usr/local/bin/

### Setup LXDE

    # add shortcut
    cp home/pi/Desktop/* /home/pi/Desktop/

### Setup supervisor

    sudo apt-get install supervisor
    # for master dashboard (do all external requests and own the redis db)
    sudo cp etc/supervisor/conf.d/dashboard_master.conf /etc/supervisor/conf.d/
    # for slave dashboard (connect to master redis db and sync all files with master)
    sudo cp etc/supervisor/conf.d/dashboard_slave.conf /etc/supervisor/conf.d/
    # reload conf
    sudo supervisorctl update

### Setup remote access

    sudo apt-get install x11vnc
    # create password
    x11vnc -storepasswd
    # launch server as you want
    x11vnc -usepw -forever &

### Setup for auto sync files (multi-screen case)

    # create ssh key and copy it to central dashboard (file src at 192.168.0.60)
    ssh-keygen
    ssh-copy-id pi@192.168.0.60
    # now we can manually sync hot file (change frequently)
    rsync -aAxX --delete --omit-dir-times 192.168.0.60:/media/ramdisk/. /media/ramdisk/.
    # and cold file
    rsync -aAxX --delete 192.168.0.60:/home/pi/dashboard/. /home/pi/dashboard/.
    # see scripts/dashboard_sync_files.py to automate this

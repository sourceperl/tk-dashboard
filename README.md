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

### Copy config file (URL, API credentials, misc...)

    # edit home/pi/.dashboard_config_sample with credentials
    # save as .dashboard_config
    cp home/pi/.dashboard_config /home/pi/

### Setup

    sudo pip3 install -r requirements.txt
    sudo cp -r scripts/* /usr/local/bin/

### Setup supervisor :

    sudo apt-get install supervisor
    sudo cp etc/supervisor/conf.d/* /etc/supervisor/conf.d/
    sudo supervisorctl update

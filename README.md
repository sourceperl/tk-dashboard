# tk-dashboard

### Create RAM disk space

    # create a 16M RAM disk (file system in RAM: tmpfs) in /media/ramdisk/
    sudo mkdir -p /media/ramdisk/
    # add line for mount RAMDISK at system startup if not already exist
    LINE='tmpfs           /media/ramdisk  tmpfs   defaults,size=16M 0       0'
    FILE='/etc/fstab'
    sudo grep -q "$LINE" "$FILE" || echo "$LINE" | sudo tee -a "$FILE"


### Copy config file (URL, API credentials, misc...)

    cp home/pi/.dashboard_config /home/pi/

### Setup

    sudo apt-get install supervisor
    sudo pip3 install -r requirements.txt

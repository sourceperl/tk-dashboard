FROM debian:buster-slim

# setup timezone to Europe/Paris
RUN ln -sf /usr/share/zoneinfo/Europe/Paris /etc/localtime
RUN dpkg-reconfigure -f noninteractive tzdata

# packages install
RUN apt-get update --quiet && apt-get upgrade --yes
RUN apt-get install --yes \
                    git \
                    fonts-freefont-ttf \
                    python3 \
                    python3-pip \
                    python3-tz \
                    python3-dateutil \
                    python3-redis \
                    python3-urllib3 \
                    python3-requests \ 
                    python3-requests-oauthlib \
                    python3-bs4 \
                    python3-feedparser \
                    python3-numpy \
                    python3-matplotlib \
                    python3-pil \
    && apt-get clean

# add python job scheduler
RUN pip3 install schedule==1.1.0

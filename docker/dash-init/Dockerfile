FROM debian:buster-slim

# setup timezone to Europe/Paris
RUN ln -sf /usr/share/zoneinfo/Europe/Paris /etc/localtime
RUN dpkg-reconfigure -f noninteractive tzdata

# packages install
RUN apt-get update --quiet && apt-get upgrade --yes
RUN apt-get install --yes \
                    python3 \
                    python3-redis \
                    vim \
                    nano \
    && apt-get clean

# main app in /usr/src/app
WORKDIR /usr/src/app

# setup environnement
ENV PYTHONUNBUFFERED=1

# copy some init apps
COPY init-static.py ./

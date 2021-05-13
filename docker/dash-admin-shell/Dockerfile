FROM debian:buster-slim

# setup timezone to Europe/Paris
RUN ln -sf /usr/share/zoneinfo/Europe/Paris /etc/localtime
RUN dpkg-reconfigure -f noninteractive tzdata

# packages install
RUN apt-get update --quiet && apt-get upgrade --yes
RUN apt-get install --yes \
                    python3 \
                    python3-redis \
                    redis-tools \
                    vim \
                    nano \
    && apt-get clean

# setup environnement
ENV PYTHONUNBUFFERED=1

# copy some admin/init apps
COPY dash-help /usr/local/bin/
COPY dash-redis-admin /usr/local/bin/
COPY dash-init-static /usr/local/bin/

# start in /root/
WORKDIR /root/

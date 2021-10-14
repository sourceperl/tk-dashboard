FROM debian:buster-slim

# setup timezone to Europe/Paris
RUN ln -sf /usr/share/zoneinfo/Europe/Paris /etc/localtime
RUN dpkg-reconfigure -f noninteractive tzdata

# packages install
RUN apt-get update --quiet && apt-get upgrade --yes
RUN apt-get install --yes \
                    autossh \
    && apt-get clean

# env: setup defaults values
ENV SSH_ARGS "-o ServerAliveInterval=10 -o ServerAliveCountMax=3"
ENV REDIS_PORT_MAP "0.0.0.0:6379:127.0.0.1:6379"

# copy entrypoint script
COPY docker-entrypoint.sh /
RUN chmod +x docker-entrypoint.sh

# start in /root/
WORKDIR /root/

# run autossh
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD autossh -M 0 -NT -L ${REDIS_PORT_MAP} ${SSH_TARGET}

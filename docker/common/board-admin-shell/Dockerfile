FROM board-py3-base-img

# packages install
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get install --yes \
                    redis-tools/buster-backports \
                    vim \
                    nano \
    && apt-get clean

# setup environnement
ENV PYTHONUNBUFFERED=1

# copy board-* tools
COPY board-* /usr/local/bin/

# copy entrypoint script
COPY docker-entrypoint.sh /

# start in /root/
WORKDIR /root/

# define command
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["bash"]
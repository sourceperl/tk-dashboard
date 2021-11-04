FROM board-py3-base-img

# add debian backports
RUN echo 'deb http://deb.debian.org/debian buster-backports main' > /etc/apt/sources.list.d/backports.list
RUN apt-get update

# packages install
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
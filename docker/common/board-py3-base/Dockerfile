FROM board-debian-base-img

# packages install
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get install --yes \
                    git \
                    fonts-freefont-ttf \
                    python3 \
                    python3-pip \
                    python3-tz \
                    python3-dateutil \
                    python3-urllib3 \
                    python3-requests \
                    python3-requests-oauthlib \
                    python3-bs4 \
                    python3-feedparser \
                    python3-numpy \
                    python3-matplotlib \
                    python3-pil \
    && apt-get clean

# add python packages
RUN pip3 install redis==3.5.3
RUN pip3 install schedule==1.1.0

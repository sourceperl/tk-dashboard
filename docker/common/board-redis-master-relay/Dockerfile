FROM board-py3-base-img

# packages install
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get install --yes autossh && apt-get clean

# main app in /usr/src/app
WORKDIR /usr/src/app

# setup environment
ENV PYTHONUNBUFFERED=1

# run app
COPY app.py ./
CMD [ "python3", "./app.py" ]

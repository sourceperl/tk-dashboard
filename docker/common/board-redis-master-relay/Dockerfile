FROM board-py3-base-img

# packages install
RUN apt-get update --quiet && apt-get upgrade --yes
RUN apt-get install --yes \
                    autossh \
    && apt-get clean

# main app in /usr/src/app
WORKDIR /usr/src/app

# setup environment
ENV PYTHONUNBUFFERED=1

# run app
COPY app.py ./
CMD [ "python3", "./app.py" ]

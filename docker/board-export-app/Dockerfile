FROM board-py3-base-img

# main app in /usr/src/app
WORKDIR /usr/src/app

# avoid to run python app as root
ARG username=py-app
RUN groupadd -r $username && \
    useradd --no-log-init -r -g $username $username
USER $username

# setup environment
ENV PYTHONUNBUFFERED=1

# run app
COPY app.py ./
CMD [ "python3", "./app.py" ]

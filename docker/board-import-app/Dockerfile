FROM board-py3-base-img

# main app in /usr/src/app
WORKDIR /usr/src/app

# add python app requirements
RUN pip3 install metar==1.8.0
RUN pip3 install wordcloud==1.8.1

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

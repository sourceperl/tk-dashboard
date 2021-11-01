FROM board-py3-base-img

# main app in /usr/src/app
WORKDIR /usr/src/app

# add python app requirements
RUN pip3 install metar==1.8.0
RUN pip3 install wordcloud==1.8.1

# avoid to run python app as root
ARG username=py-app
RUN useradd -m $username
USER $username

# setup environment
ENV PYTHONUNBUFFERED=1

# first matplotlib font_manager import to populate user directory (generating new fontManager)
RUN python3 -c 'import matplotlib.font_manager'

# run app
COPY app.py ./
CMD [ "python3", "./app.py" ]

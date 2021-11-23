FROM board-py3-base-img

# main app in /usr/src/app
WORKDIR /usr/src/app

# add python app requirements
RUN pip3 install git+git://github.com/sourceperl/pyHMI@v0.0.7

# avoid to run python app as root
ARG username=py-app
RUN useradd -m $username
USER $username

# setup environment
ENV PYTHONUNBUFFERED=1

# run app
COPY loos/board-meters-app/board_lib.py ./
COPY loos/board-meters-app/app.py ./
CMD [ "python3", "./app.py" ]

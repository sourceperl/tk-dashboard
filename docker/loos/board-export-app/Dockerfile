FROM board-py3-base-img

# main app in /usr/src/app
WORKDIR /usr/src/app

# avoid to run python app as root
ARG username=py-app
RUN useradd -m $username
USER $username

# setup environment
ENV PYTHONUNBUFFERED=1

# run app
COPY loos/board-export-app/board_lib.py ./
COPY loos/board-export-app/app.py ./
CMD [ "python3", "./app.py" ]

FROM board-py3-base-img

# main app in /usr/src/app
WORKDIR /usr/src/app

# packages install
ARG DEBIAN_FRONTEND=noninteractive
# python package pdf2image need poppler-utils debian package
RUN apt-get install --yes poppler-utils && apt-get clean

# add python app requirements
RUN pip3 install metar==1.8.0
RUN pip3 install pdf2image==1.16.0

# avoid to run python app as root
ARG username=py-app
RUN useradd -m $username
USER $username

# setup environment
ENV PYTHONUNBUFFERED=1

# first matplotlib font_manager import to populate user directory (generating new fontManager)
RUN python3 -c 'import matplotlib.font_manager'

# run app
COPY common/python-lib/webdav.py ./
COPY messein/board-import-app/app.py ./
CMD [ "python3", "./app.py" ]

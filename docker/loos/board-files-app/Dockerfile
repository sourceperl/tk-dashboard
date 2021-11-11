FROM board-py3-base-img

# packages install
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get install --yes imagemagick && apt-get clean

# main app in /usr/src/app
WORKDIR /usr/src/app

# avoid to run python app as root
# ARG username=py-app
# RUN useradd -m $username
# USER $username

# fix ImageMagick policy for pdf -> png convert
# see https://stackoverflow.com/questions/52861946/imagemagick-not-authorized-to-convert-pdf-to-an-image
RUN sed -i 's/<policy.*coder.*none.*PDF.*\/>/<!--&-->/' /etc/ImageMagick-6/policy.xml

# setup environment
ENV PYTHONUNBUFFERED=1

# run app
COPY app.py ./
CMD [ "python3", "./app.py" ]

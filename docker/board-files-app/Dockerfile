FROM debian:buster-slim

# setup timezone to Europe/Paris
RUN ln -sf /usr/share/zoneinfo/Europe/Paris /etc/localtime
RUN dpkg-reconfigure -f noninteractive tzdata

# packages install
RUN apt-get update --quiet && apt-get upgrade --yes
RUN apt-get install --yes \
                    python3 \
                    python3-pip \
                    python3-tz \
                    python3-dateutil \
                    python3-redis \
                    python3-urllib3 \
                    python3-requests \ 
                    python3-requests-oauthlib \
                    python3-pil \
                    imagemagick \
    && apt-get clean

# main app in /usr/src/app
WORKDIR /usr/src/app

# add python app requirements
COPY requirements.txt ./
RUN pip3 install -r requirements.txt

# avoid to run python app as root
# ARG username=py-app
# RUN groupadd -r $username && \
#     useradd --no-log-init -r -g $username $username
# USER $username

# fix ImageMagick policy for pdf -> png convert
# see https://stackoverflow.com/questions/52861946/imagemagick-not-authorized-to-convert-pdf-to-an-image
RUN sed -i 's/<policy.*coder.*none.*PDF.*\/>/<!--&-->/' /etc/ImageMagick-6/policy.xml

# setup environment
ENV PYTHONUNBUFFERED=1

# run app
COPY app.py ./
CMD [ "python3", "./app.py" ]
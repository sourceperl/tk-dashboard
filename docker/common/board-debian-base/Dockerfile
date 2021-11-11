FROM debian:buster-slim

# add debian backports
RUN echo 'deb http://deb.debian.org/debian buster-backports main' > /etc/apt/sources.list.d/backports.list

# update packages database
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update -qq && apt-get upgrade --yes

# setup timezone to Europe/Paris
RUN ln -sf /usr/share/zoneinfo/Europe/Paris /etc/localtime
RUN dpkg-reconfigure -f noninteractive tzdata

FROM debian:stable
WORKDIR /britney
ADD . /britney
RUN apt-get update && apt-get install --no-install-recommends --assume-yes python3 python3-apt python3-yaml python3-coverage python3-nose rsync libclass-accessor-perl libdpkg-perl curl

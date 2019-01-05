FROM debian:stable
WORKDIR /britney
ADD . /britney
RUN apt-get update && apt-get install --no-install-recommends --assume-yes python3 python3-apt python3-yaml python3-coverage python3-nose python3-pycodestyle rsync libclass-accessor-perl libdpkg-perl libyaml-syck-perl curl

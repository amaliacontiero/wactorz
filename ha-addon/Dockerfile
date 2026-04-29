ARG BUILD_FROM=ghcr.io/home-assistant/aarch64-base-python:3.12-alpine3.20
FROM $BUILD_FROM

RUN apk add --no-cache \
    curl git jq gcc musl-dev linux-headers libffi-dev openssl-dev \
    openjdk17-jre-headless \
    mosquitto mosquitto-clients

# Fuseki — embedded SPARQL triplestore (opt-in at runtime via fuseki_embedded option)
# Version matches config/fuseki-container/Containerfile (known-good with shiro 2.x auth)
ARG FUSEKI_VERSION=5.0.0
RUN curl -fsSL \
    "https://archive.apache.org/dist/jena/binaries/apache-jena-fuseki-${FUSEKI_VERSION}.tar.gz" \
    | tar -xz -C /opt \
    && mv "/opt/apache-jena-fuseki-${FUSEKI_VERSION}" /opt/fuseki \
    && chmod +x /opt/fuseki/fuseki-server

# BUILD_VERSION is passed by HA Supervisor — referencing it here busts the
# Docker layer cache whenever the addon version is bumped in config.yaml.
ARG BUILD_VERSION=main
RUN pip3 install --no-cache-dir "wactorz[all] @ git+https://github.com/waldiez/wactorz.git@main" \
    && echo "wactorz addon ${BUILD_VERSION} installed"

COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]

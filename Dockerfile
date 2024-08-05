FROM texlive/texlive:latest

# Volumes for mounting the reports and templates
VOLUME /reports
VOLUME /templates

USER root

COPY . /usr/src/sereto

RUN apt-get -y update && \
    apt-get install -y pandoc python3-pip pipx vim && \
    pipx install /usr/src/sereto/ && \
    apt-get clean && \
    rm -rf /var/cache/apt/* && rm -rf /var/lib/apt/lists/* && rm -rf /tmp/* && \
    mkdir -p /root/.config/sereto && \
    echo '{"reports_path": "/reports", "templates_path": "/templates"}' > /root/.config/sereto/settings.json

# Expose pipx location to the PATH
ENV PATH="/root/.local/bin:${PATH}"

CMD ["/bin/bash"]

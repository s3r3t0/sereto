FROM texlive/texlive:latest

# Volumes for mounting the reports and templates
VOLUME /reports
VOLUME /templates

USER root

COPY . /usr/src/sereto

# Install sereto and its dependencies, create user "sereto"
RUN useradd -m sereto && \
    apt-get -y update && \
    apt-get install -y pandoc python3-pip pipx vim && \
    pipx install --global /usr/src/sereto/ && \
    apt-get clean && \
    rm -rf /var/cache/apt/* && \
    rm -rf /var/lib/apt/lists/* && \
    rm -rf /tmp/* && \
    rm -rf /usr/src/sereto && \
    mkdir -p /home/sereto/.config/sereto && \
    echo '{"reports_path": "/reports", "templates_path": "/templates"}' > /home/sereto/.config/sereto/settings.json && \
    chown -R sereto:sereto /home/sereto/.config

# Switch to sereto user
USER sereto
WORKDIR /home/sereto

# Default command
CMD ["/bin/bash"]

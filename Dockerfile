FROM texlive/texlive:latest

# Volumes for mounting the projects and templates
VOLUME /projects
VOLUME /templates

USER root

COPY . /usr/src/sereto

RUN \
    # Install system dependencies and sereto
    apt-get -y update && \
    apt-get install -y pandoc python3-pip python3-venv vim gosu && \
    python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install /usr/src/sereto/ && \
    # Prepare container entrypoint script
    cp /usr/src/sereto/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh && \
    chmod +x /usr/local/bin/docker-entrypoint.sh && \
    # Clean up apt cache and temporary files
    apt-get clean && \
    rm -rf /var/cache/apt/* /var/lib/apt/lists/* /tmp/* /root/.cache/pip && \
    rm -rf /usr/src/sereto && \
    # Create default settings
    mkdir -p /home/sereto/.config/sereto && \
    echo '{\n  "projects_path": "/projects",\n  "templates_path": "/templates"\n}' > /home/sereto/.config/sereto/settings.json

ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /home/sereto

# Entry point adjusts group permissions for mounted volumes and starts CMD as low-privileged user
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["sereto", "repl"]

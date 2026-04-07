FROM pandoc/typst:latest@sha256:90002c55474653351fd99d94fcd4e830c236440c2b51b22862ec96f6c9dd1560

# Volumes for mounting the projects and templates
VOLUME /projects
VOLUME /templates

USER root

COPY . /usr/src/sereto

RUN \
    # Install system dependencies and sereto
    apk add --no-cache \
        python3 \
        py3-pip \
        vim \
        gosu \
    && \
    python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install /usr/src/sereto/ && \
    # Prepare container entrypoint script
    cp /usr/src/sereto/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh && \
    chmod +x /usr/local/bin/docker-entrypoint.sh && \
    # Clean up temporary files
    rm -rf /tmp/* /root/.cache/pip && \
    rm -rf /usr/src/sereto && \
    # Create default settings
    mkdir -p /home/sereto/.config/sereto && \
    printf '{\n  "projects_path": "/projects",\n  "templates_path": "/templates"\n}\n' > /home/sereto/.config/sereto/settings.json

ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /home/sereto

# Entry point adjusts group permissions for mounted volumes and starts CMD as low-privileged user
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["sereto", "repl"]

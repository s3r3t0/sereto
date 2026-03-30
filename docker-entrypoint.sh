#!/usr/bin/env sh
set -e

# Add a low-privileged user to run the application
USER_ID=$(stat -c '%u' /projects 2>/dev/null || echo 1000)
if [ "$USER_ID" = "0" ]; then
    USER_ID=1000
fi
adduser -D -h /home/sereto -u "$USER_ID" sereto

# Change permissions
chown -R sereto:sereto /home/sereto/

# Add sereto user to the group of /projects if it exists
if [ -d /projects ]; then
    PROJECTS_GID=$(stat -c '%g' /projects)
    if ! getent group "$PROJECTS_GID" >/dev/null 2>&1; then
        addgroup -g "$PROJECTS_GID" projectsgrp
    fi
    addgroup sereto "$(getent group "$PROJECTS_GID" | cut -d: -f1)"
fi

# Add sereto user to the group of /templates if it exists
if [ -d /templates ]; then
    TEMPLATES_GID=$(stat -c '%g' /templates)
    if ! getent group "$TEMPLATES_GID" >/dev/null 2>&1; then
        addgroup -g "$TEMPLATES_GID" templatesgrp
    fi
    addgroup sereto "$(getent group "$TEMPLATES_GID" | cut -d: -f1)"
fi

# Install requirements from /templates/requirements.txt if it exists
if [ -f /templates/requirements.txt ]; then
    /opt/venv/bin/pip install -r /templates/requirements.txt
fi

exec gosu sereto "$@"

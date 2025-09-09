#!/usr/bin/env bash
set -e

# Add a low-privileged user to run the application
USER_ID=$(stat -c '%u' /projects 2>/dev/null || echo 1000)
useradd -m -u "$USER_ID" --non-unique sereto

# Change permissions
chown -R sereto:sereto /home/sereto/

# Add sereto user to the group of /projects if it exists
if [ -d /projects ]; then
    PROJECTS_GID=$(stat -c '%g' /projects)
    if ! getent group "$PROJECTS_GID" >/dev/null; then
        groupadd -g "$PROJECTS_GID" projectsgrp
    fi
    usermod -aG "$PROJECTS_GID" sereto
fi

# Add sereto user to the group of /templates if it exists
if [ -d /templates ]; then
    TEMPLATES_GID=$(stat -c '%g' /templates)
    if ! getent group "$TEMPLATES_GID" >/dev/null; then
        groupadd -g "$TEMPLATES_GID" templatesgrp
    fi
    usermod -aG "$TEMPLATES_GID" sereto
fi

# Install requirements from /templates/requirements.txt if it exists
if [ -f /templates/requirements.txt ]; then
    /opt/venv/bin/pip install -r /templates/requirements.txt
fi

exec gosu sereto "$@"

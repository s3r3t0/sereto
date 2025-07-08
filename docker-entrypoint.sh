#!/bin/bash
set -e

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

exec gosu sereto "$@"

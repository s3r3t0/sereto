FROM sereto/sereto

USER root

# Install vhs dependencies and vhs itself
RUN apt-get update && apt-get -y install ffmpeg chromium
COPY --from=tsl0922/ttyd /usr/bin/ttyd /usr/bin/
COPY --from=ghcr.io/charmbracelet/vhs /usr/bin/vhs /usr/bin/

USER sereto

# Setup sereto environment
RUN mkdir "$HOME/projects"
RUN git clone https://github.com/s3r3t0/templates.git "$HOME/templates"
RUN echo "{\n  \"projects_path\": \"$HOME/projects\",\n  \"templates_path\": \"$HOME/templates\"\n}" > "$HOME/.config/sereto/settings.json"

WORKDIR /vhs

ENV VHS_NO_SANDBOX "true"

ENTRYPOINT ["/usr/bin/vhs"]

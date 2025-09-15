# Documentation

## Serving the documentation locally

Install dependencies and start the live preview server:

```sh
uv run --with '.[docs]' mkdocs serve
```

Then open the URL shown in the terminal output (typically [http://127.0.0.1:8000](http://127.0.0.1:8000)).

The server auto-reloads when you edit Markdown or configuration files.

Optional:

- Change host/port: `uv run --with '.[docs]' mkdocs serve -a 0.0.0.0:8001`
- Only build without starting the server: `uv run --with '.[docs]' mkdocs build` (outputs to the `site/` directory)
- Clean previous build: remove the `site/` directory before building if needed


## Writing documentation

### Generating GIFs

We use [VHS](https://github.com/charmbracelet/vhs) to record GIFs for the documentation. A `Dockerfile` is provided in the `docs/assets/gifs/` directory to simplify the process of recording and generating GIFs.

To build the Docker image, run:
```sh
cd docs/assets/gifs/
docker build -t vhs -f vhs.Dockerfile .
```

With the following command, the GIF can be recorded based on the provided `.tape` file:
```sh
docker run --rm -v "$PWD:/vhs" vhs new-project.tape
```

Since the docker is running with a low-privileged user, `vhs` may have problems writing to the specified volume. On Linux, this can be fixed by adding extended permissions to the directory for user with UID 1001, e.g.:
```sh
setfacl -m u:1001:rwx .
```

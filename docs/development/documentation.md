# Documentation

To serve the documentation locally, you need to:

1. Install the dependencies
    ```sh
    pip install "sereto[docs]"
    ```

2. Start a local client
    ```sh
    mkdocs serve
    ```

3. Open the URL presented in the terminal as the output of the previous command, typically [http://127.0.0.1:8000](http://127.0.0.1:8000/).


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
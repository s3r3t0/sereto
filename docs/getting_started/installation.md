# Installation

## System Requirements

- Python 3.10+


## Install dependencies

### [`pipx`](https://pipx.pypa.io/stable/installation/)

> You might skip this step if you know what you are doing and prefer other methods of installation for Python packages.

=== "Ubuntu 23.04 or above"
    ```sh
    sudo apt update
    sudo apt install pipx
    pipx ensurepath
    sudo pipx ensurepath --global  # optional to allow pipx actions in global scope.
    ```

=== "Fedora"
    ```sh
    sudo dnf install pipx
    pipx ensurepath
    sudo pipx ensurepath --global # optional to allow pipx actions in global scope.
    ```

=== "Pip"
    ```sh
    python3 -m pip install --user pipx
    python3 -m pipx ensurepath
    sudo pipx ensurepath --global # optional to allow pipx actions in global scope.
    ```

### TeX Live

=== "Ubuntu"
    ```sh
    sudo apt install texlive-full
    ```

=== "Fedora"
    ```sh
    sudo dnf install texlive-scheme-full
    ```

### Pandoc

> Pandoc is used as a default command for transformation of markdown files.

=== "Ubuntu"
    ```sh
    sudo apt install pandoc
    ```

=== "Fedora"
    ```sh
    sudo dnf install pandoc
    ```

## Install SeReTo

=== "PyPI"
    ```sh
    pipx install sereto
    ```

=== "GitHub"
    ```sh
    git clone https://github.com/s3r3t0/sereto.git
    cd sereto
    pipx install .
    ```

## Docker

Alternatively you can use SeReTo in a Docker container. You will need to mount the directories with reports and templates to the container.

=== "DockerHub"
    ```sh
    docker run -it --rm -v "<path_to_reports>:/reports" -v "<path_to_templates>:/templates" sereto/sereto
    ```

=== "Build"
    ```sh
    docker build . -t sereto
    docker run -it --rm -v "<path_to_reports>:/reports" -v "<path_to_templates>:/templates" sereto
    ```

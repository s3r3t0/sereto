# Installation

## System Requirements

- Python 3.11+


## Install dependencies

### Common

#### [`uv`](https://docs.astral.sh)

> You might skip this step if you know what you are doing and prefer other methods of installation for Python packages (e.g. `pip`).

For installation instructions visit: [https://docs.astral.sh/uv/getting-started/installation/](https://docs.astral.sh/uv/getting-started/installation/)

#### Pandoc

> Pandoc is used as a default command for transformation of markdown files to TeX.

For installation instructions visit: [https://pandoc.org/installing.html](https://pandoc.org/installing.html)

E.g.:

=== "Ubuntu"
    ```sh
    sudo apt install pandoc
    ```

=== "Fedora"
    ```sh
    sudo dnf install pandoc
    ```

=== "Windows"
    ```cmd
    winget install --source winget --exact --id JohnMacFarlane.Pandoc
    ```

For certain installations (e.g., using `uv`), it is recommended to install the `pandocfilters` package system-wide. This is because the Pandoc tool is executed in a new process, which will not have access to SeReTo dependencies.

```sh
pip install pandocfilters
```

### Linux

> First see [Common](#common) section.

#### TeX Live

> TeX Live is a distribution of the TeX/LaTeX typesetting system.

=== "Ubuntu"
    ```sh
    sudo apt install texlive-full
    ```

=== "Fedora"
    ```sh
    sudo dnf install texlive-scheme-full
    ```

### Windows

> First see [Common](#common) section.

#### MikTeX

> MikTeX is a distribution of the TeX/LaTeX typesetting system for Microsoft Windows.

For installation instructions visit: [https://miktex.org/download](https://miktex.org/download)

#### Perl

> Perl is a programming language that is commonly used for text manipulation.

Install e.g. Strawberry Perl from: [https://strawberryperl.com/](https://strawberryperl.com/)


## Install SeReTo

=== "PyPI"
    ```sh
    uv tool install sereto
    ```

=== "GitHub"
    ```sh
    uv tool install git+https://github.com/s3r3t0/sereto
    ```

## Docker

Alternatively you can use SeReTo in a Docker container. You will need to mount the directories with projects and templates to the container.

=== "DockerHub"
    ```sh
    docker run -it --rm -v "<path_to_projects>:/projects" -v "<path_to_templates>:/templates" sereto/sereto
    ```

=== "Build"
    ```sh
    docker build . -t sereto
    docker run -it --rm -v "<path_to_projects>:/projects" -v "<path_to_templates>:/templates" sereto
    ```

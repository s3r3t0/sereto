# Installation

## System Requirements

- Python 3.10+


## Install dependencies

### [`pipx`](https://pipx.pypa.io/stable/installation/)

- Ubuntu 23.04 or above:
```
sudo apt update
sudo apt install pipx
pipx ensurepath
sudo pipx ensurepath --global # optional to allow pipx actions in global scope. See "Global installation" section below.
```

- Fedora:
```
sudo dnf install pipx
pipx ensurepath
sudo pipx ensurepath --global # optional to allow pipx actions in global scope. See "Global installation" section below.
```

- Using `pip` on other distributions:
```
python3 -m pip install --user pipx
python3 -m pipx ensurepath
sudo pipx ensurepath --global # optional to allow pipx actions in global scope. See "Global installation" section below.
```

### TeX Live

- Ubuntu:
```
sudo apt install texlive-full
```

- Fedora:
```
sudo dnf install texlive-scheme-full
```

### Pandoc

> Pandoc is used as a default command for transformation of markdown files.

- Ubuntu:
```
sudo apt install pandoc
```

- Fedora:
```
sudo dnf install pandoc
```

## Install SeReTo
```
pipx install .
```

## Docker (development)

Alternatively you can use SeReTo in a Docker container. <!-- The image is available on [Docker Hub](TODO URL). -->
You will need to mount the directories with reports and templates to the container.

```
docker build . -t sereto
docker run -it --rm -v "<path_to_reports>:/reports" -v "<path_to_templates>:/templates" sereto
```

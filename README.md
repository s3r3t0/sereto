# Security Reporting Tool

> Created with support of [NN Management Services, s.r.o.](https://www.nn.cz/kariera/en/it-hub/)

## Development

### Tox

Run tests and linters:

```sh
tox
```

Format code:

```sh
tox -e format
```

### Documentation

Install dependencies:

```sh
pip install mkdocs-material
pip install "mkdocstrings[python]"
```

Start local client:

```sh
mkdocs serve
```

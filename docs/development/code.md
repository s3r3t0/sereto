# Code

## Development

It is recommended to create a persistent `.venv` directory for development (`uv` can handle also ephemeral envs):

```sh
uv venv .venv
source .venv/bin/activate

# install SeReTo in editable mode
uv pip install -e ".[dev]"

# install template dependencies
uv pip install -r <path>/templates/requirements.txt
```

## Format

We are using `ruff` to automatically format the code. The command is defined as an environment in Tox:

```sh
tox -e format
```

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

## Install the git hook scripts

The project uses [pre-commit](https://pre-commit.com/) to run automated checks before each commit. The hooks are configured in `.pre-commit-config.yaml` and include:

- Trailing whitespace removal
- End-of-file fixer
- TOML validation
- Ruff formatting

To install the git hook scripts:

```sh
pre-commit install
```

Once installed, the hooks will run automatically before each commit. You can also run them manually:

```sh
# Run on all files
pre-commit run --all-files

# Run on staged files only
pre-commit run
```

## Format

We are using `ruff` to automatically format the code. The command is defined as an environment in Tox:

```sh
tox -e format
```

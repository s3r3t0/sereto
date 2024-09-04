# Tests

We are using [Tox](https://tox.wiki) to run all the tests with a single command:

```sh
tox
```

This will:

- **lint** the code with `ruff`
- perform **type** checking with `mypy`
- run **tests** for several supported Python versions using `pytest`

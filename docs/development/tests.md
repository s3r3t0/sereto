# Tests

We are using [Tox](https://tox.wiki) to run all the tests with a single command:

```sh
tox
```

This will:

- **lint** the code with `ruff`
- perform **type** checking with `mypy`
- run **tests** for several supported Python versions using `pytest`

The test matrix covers Python 3.12, 3.13, 3.14, and 3.15; the minimum supported version remains Python 3.12.
Tox skips interpreters that are not installed locally. To test Python 3.15 specifically, run `tox -e py315`.
CI also tests the locked dependencies on Python 3.15 without C/C++ compilers.

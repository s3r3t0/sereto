# Tests

We are using [Tox](https://tox.wiki) to run all the tests with a single command:

```sh
tox
```

This will:

- **lint** the code (`sereto` and `tests`) with `ruff`, including the [flake8-bandit](https://docs.astral.sh/ruff/rules/#flake8-bandit-s) security rules
- perform **type** checking with `mypy` and `ty`
- run the **pre-commit** hooks on all files
- run **tests** for several supported Python versions using `pytest`

The test matrix covers Python 3.12, 3.13, 3.14, and 3.15; the minimum supported version remains Python 3.12.
Tox skips interpreters that are not installed locally. To test Python 3.15 specifically, run `tox -e py315`.
CI also tests the locked dependencies on Python 3.15 without C/C++ compilers.

## Security lint findings

Fix the code rather than suppressing a security rule. If a finding is a false positive (e.g. HTML autoescaping for TeX templates), suppress it on that line with `# noqa: S<code>` and explain why in a comment.

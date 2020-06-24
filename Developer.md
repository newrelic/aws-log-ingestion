# Setup Python Environment

- Install `pipenv` using brew: `brew install pipenv`
- Create virtualenv and install dependencies with `pipenv install --dev --deploy`

# Running tests and linter locally

- Run tests with `pipenv run pytest`
- Ensure the code is PEP-8 compliant by using the flake8 linter: `pipenv run flake8`

# Publishing a new version

To publish a new version [create a release](https://github.com/newrelic/aws-log-ingestion/releases/new)
and specify a tag that matches the `SemanticVersion` that appears in the `template.yml`
but prefixed with a `v`. For example, if the `SemanticVersion` is `1.2.3` then your
release tag should be `v1.2.3`.

# Code style

We use the [black](https://github.com/psf/black) code formatter.

```bash
pip install black
```

We recommend using it with [pre-commit](https://pre-commit.com/#install):

```bash
pip install pre-commit
pre-commit install
```

Using these together will auto format your git commits.

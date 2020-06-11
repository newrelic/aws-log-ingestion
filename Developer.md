# Setup Python Environment

- Install `pipenv` using brew: `brew install pipenv`
- Create virtualenv and install dependencies with `pipenv install --dev --deploy`

# Running tests and linter locally

- Run tests with `pipenv run pytest`
- Ensure the code is PEP-8 compliant by using the flake8 linter: `black .; pipenv run flake8`

# Publishing a new version

Currently a manual process. Follow carefully.

> Each NEW PR must be approved by the Lambda team and the Logs team

- Make sure that you've updated the semantic version in the template.yaml file.
- Use the build.sh script, which does the following:
  - Generate the requirements.txt with `pipenv lock --requirements --keep-outdated > ./src/requirements.txt`,
  - Use `sam build --use-container`
- To package and upload the Lambda to an S3 bucket,  
`sam package --s3-bucket nr-serverless-applications --output-template-file packaged.yaml`. You'll need access to the `nr-dashboards` AWS account.
- `sam publish --region us-east-1 --template packaged.yaml` to publish the serverless repo application
- Double check that everything is working as expected by creating a new function based on that app and check that it's using latest version of code. The publish step is kinda flakey; you may need to do that from the AWS Console UI.

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

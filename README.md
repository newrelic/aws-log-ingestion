[![Community Project header](https://github.com/newrelic/open-source-office/raw/master/examples/categories/images/Community_Project.png)](https://github.com/newrelic/open-source-office/blob/master/examples/categories/index.md#community-project)

# New Relic CloudWatch Logs ingestion

AWS Serverless application that sends log data from CloudWatch Logs to New Relic.

## Requirements

To forward data to New Relic you need a [New Relic License Key](https://docs.newrelic.com/docs/accounts/install-new-relic/account-setup/license-key).

## Install and configure

To install and configure the New Relic Cloudwatch Logs Lambda, [see our documentation](https://docs.newrelic.com/docs/logs/enable-logs/enable-logs/aws-cloudwatch-plugin-logs).

## Manual Deployment

If your organization restricts access to deploy via SAR, follow these steps below
to deploy the log ingestion function manually.

### SAM

1. Clone this repository: `git clone https://github.com/newrelic/aws-log-ingestion.git`
2. [Install the SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html)
3. [Retrieve your New Relic License Key](https://docs.newrelic.com/docs/accounts/install-new-relic/account-setup/license-key)
4. Build the SAM application (if on Linux `-u` can be omitted): `sam build -u --parameter-overrides 'ParameterKey=NRLicenseKey,ParameterValue=your-license-key-here'`
5. Deploy the SAM application: `sam deploy --guided`

Additional notes:

* To set `LOGGING_ENABLED`: `sam build ... --parameter-overrides 'ParameterKey=NRLoggingEnabled,ParameterValue=True'`

### Serverless

1. Clone this repository: `git clone https://github.com/newrelic/aws-log-ingestion.git`
2. Install Serverless: `npm install -g serverless`
3. Install the serverless-python-requirements plugin: `sls plugin install -n serverless-python-requirements`
4. If not running Linux, [install Docker](https://docs.docker.com/install/)
5. [Retrieve your New Relic License Key](https://docs.newrelic.com/docs/accounts/install-new-relic/account-setup/license-key)
6. Set the LICENSE_KEY environment variable: `export LICENSE_KEY=your-license-key-here`
7. Deploy the function: `sls deploy`

Additional notes:

* To set `LOGGING_ENABLED`: `export LOGGING_ENABLED=True` (prior to deploy)

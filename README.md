[![Community Project header](https://github.com/newrelic/open-source-office/raw/master/examples/categories/images/Community_Project.png)](https://github.com/newrelic/open-source-office/blob/master/examples/categories/index.md#community-project)

# New Relic CloudWatch Logs ingestion

AWS Serverless application that sends log data from CloudWatch Logs to New Relic.

## Requirements

To forward data to New Relic you need a [New Relic License Key](https://docs.newrelic.com/docs/accounts/install-new-relic/account-setup/license-key).

## Install and configure

To install and configure the New Relic Cloudwatch Logs Lambda, [see our documentation](https://docs.newrelic.com/docs/logs/enable-logs/enable-logs/aws-cloudwatch-plugin-logs).

Additional notes:

* Some users in UTF-8 environments have reported difficulty with defining strings of `NR_TAGS` delimited by the semicolon `;` character. If this applies to you, you can set an alternative delimiter character as the value of `NR_ENV_DELIMITER`, and separate your `NR_TAGS` with that.
* Custom Lambda and VPC log groups can be set using the `NR_LAMBDA_LOG_GROUP_PREFIX` and `NR_VPC_LOG_GROUP_PREFIX` environment variables.
* The New Relic License Key can now be fetched from multiple secure sources:

- **Environment Variables**
- **AWS Systems Manager (SSM) Parameter Store**
- **AWS Secrets Manager**

A caching mechanism has also been added to store the New Relic License Key. This prevents fetching the key from AWS Secrets Manager or SSM Parameter Store on each Lambda execution, improving performance.

## Manual Deployment

If your organization restricts access to deploy via SAR, follow these steps below
to deploy the log ingestion function manually.

### SAM

1. Clone this repository: `git clone https://github.com/newrelic/aws-log-ingestion.git`
2. [Install the SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html) Make sure you have >=1.105.0 installed, you can check with `sam --version`.
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

### Terraform

In your Terraform, you can add this as a module, replacing `{{YOUR_LICENSE_KEY}}` with your New Relic License Key.

```terraform
module "newrelic_log_ingestion" {
  source             = "github.com/newrelic/aws-log-ingestion"
  nr_license_key     = "{{YOUR_LICENSE_KEY}}"
}
```

By default, this will build and pack the lambda zip inside of the Terraform Module. You can supply your own by switching `build_lambda = false`, and specify the path to your lambda, using `lambda_archive = "{{LAMBDA_PATH}}"`, replacing `{{LAMBDA_PATH}}` with the path to your lambda.

### Configuration Guide for New Relic License Key Retrieval

To configure the retrieval of the New Relic License Key from different sources. Follow the steps below to set up your preferred method:

1. **Select the License Key Source** : Use the `nr_license_key_source` variable to specify where the license key should be fetched from. You have three options:
   * `environment_var`: Fetches the license key from an environment variable. This is the default setting.
   * `ssm`: Retrieves the license key from AWS Systems Manager (SSM) Parameter Store.
   * `secrets_manager`: Obtains the license key from AWS Secrets Manager.
2. **Enable License Key Caching** : To improve performance by caching the New Relic License Key, set the `enable_caching_for_license_key` variable to `true`.
3. **Specify the Key Location** :
   * If you chose `ssm` or `secrets_manager` as your source in step 1, you need to provide additional information to locate the license key:
     * For `secrets_manager`: Supply the secret's name or Amazon Resource Name (ARN) to the `nr_license_key` variable.
     * For `ssm`: Provide the name of the parameter in the Parameter Store that holds the license key to the `nr_license_key` variable

- Set the `nr_license_key_source` variable to choose the source of the license key. The available options are `environment_var`, `ssm`, or `secrets_manager`. The default value is `environment_var`.
- Set the `enable_caching_for_license_key` variable to `true` to enable caching for the New Relic License Key.
- When setting `nr_license_key_source` value to either `ssm` or `secrets_manager`, secret name or secret ARN can be passed to `nr_license_key` variable to fetch the key from Secrets Manager. Parameter store, the parameter name where the license key is stored can be provided by `nr_license_key` variable.

```terraform
module "newrelic_log_ingestion" {
source                         = "github.com/newrelic/aws-log-ingestion"
nr_license_key                 = "{{ARN_OF_LICENSE_KEY_SECRET_OF_SECRETS_MANAGER}}"
nr_license_key_source          = "secrets_manager"
enable_caching_for_license_key = true
}
```

## Infra Payload Format

The maximum payload size in bytes is:

<https://github.com/newrelic/aws-log-ingestion/blob/1430a247f1fb5feb844f0707838a6ef48d21fc41/src/function.py#L76>

If your payload exceeds this size, you will need to split it into pieces:

<https://github.com/newrelic/aws-log-ingestion/blob/1430a247f1fb5feb844f0707838a6ef48d21fc41/src/function.py#L292-L306>

The payload should be utf-8 encoded and then gzipped before sending:

<https://github.com/newrelic/aws-log-ingestion/blob/1430a247f1fb5feb844f0707838a6ef48d21fc41/src/function.py#L298>

The following GNU coreutils Bash command will reproduce the desired payload encoding and compression:

```sh
xclip -sel clip -o | iconv -cf utf-8 | gzip > payload.gz
```

Required headers include:

* <https://github.com/newrelic/aws-log-ingestion/blob/1430a247f1fb5feb844f0707838a6ef48d21fc41/src/function.py#L360-L361>
* `Accept-Encoding: gzip`
* `Content-Length: <calculated when request is sent>`
* `Host: <calculated when request is sent>`

The payload should include the following (properly escaped) elements[^1]:

```json
{
  "context": {
    "function_name": "newrelic-log-ingestion",
    "invoked_function_arn": "arn:aws:lambda:<your_aws_region>:<your_aws_account>:function:newrelic-log-ingestion",
    "log_group_name": "/aws/lambda/newrelic-log-ingestion",
    "log_stream_name": "<your_nli_log_stream_name>"
  },
  "entry": "{\"messageType\": \"DATA_MESSAGE\", \"owner\": \"<your_aws_account>\", \"logGroup\": \"/aws/lambda/<your_function_name>\", \"logStream\": \"<your_function_log_stream_name>\", \"subscriptionFilters\": [\"<your_function_name>\"], \"logEvents\": [{\"id\": \"36858672311120633630098786383886689203484013407063113737\", \"timestamp\": 1652800029012, \"message\": \"[1,\\\"NR_LAMBDA_MONITORING\\\",\\\"H4sIAAAAAAAAA+1Y3W/bNhB/919hCHu0JUrUF40hQLZ2WIBiLWBveygKgZZOHjea0kjJiRvkfx8lS66s2Elqx0XXVC/U3ZG8u98djx+3g+HQWEJBE1pQYzK81bTmUCk0UTUTeq0mnC7nCZ38uM5KGWlGJGHBMnHR4dA4zkpRXEzSUsSFFjaylowEXcKFMdrMv+WuQCrdVsp+eHM5ez2dtV3gBuKy7gNixWQmliCKqt/ln9PoTW1QJLIE/la2a960o3KZFVmc8c7Ett/I6ELP0NUYmjYykaGld1UXYxcDjYpkcdQw39fM4VCUnI+af9v3nBAh5IQmsYN7XGIiRFpuO777N2xUtZ9RYVQZNi3zPJMFnTPOirX1W+2m9cfGcst2jc6wu1GHeL8znz3aIdEpZIf6sP3/MDrdq8s85yymVaSttzkIJhbWq1LWjCP9NO3AsZ0wQP4ZBTq+vhM6xHYd4mDXxe4XgehKsIJRzj5uyFORcoLw2VgoCJzQRdvPeX5ALt9dWQqKzfL/lYqEg/yWFsNMUqFoXRqVNYVFVfPUcQ46J5BnSOVpTsXrlXbHmmUF5fWvmgIcm7lfV/gOeKc3rP+ld2+Lv0B2ctH6pdmvrb2b+pG1R5cIm/iYnIePzdDzCcKO3ZQjD8YoPAM4dcRnbAnfUXoohSjnLxyCbaK8MBzaM8pP6591EoC0fhf/iOxaHGxfXqocA1GdXi8Mp/5xUFC+LlisNhvuN3m0eNDHr+iAMei2jceG0ueiCCpjH7pHfwLCkKBArjImI8U+VnA4Ons+6TfquVSkqujqq/2g5/iTbtnFOt8ArY0zRj2ZpDFcJZV47oQkTfHcRT4loRejuWN7BOyYkCTAHukPXZSsHodTm+A0BcCYpj5O9qhod4SNogAF1PPjIIXEoQH2+wMUXeYcqq6FLKEnzCXLpM6TCg3TdwPkeqP9efWZh7reLPr6CYtMVnqMBQiQLL7nmN7aVKGNrR9d2kcQvfh7/ZL2zjo5WEAMIU0daLl+l7H61WeP5x0czWc+uN7uUrt66bUyNw9i5pmfyXZUSvi31PBuUsZHCaE+xeMU2zB2Mfhj4tJgHLqhB8hPQ0rvpVHH7jjjybSg8gCyQkZwE/NSsRVEbbSiJeOcqTpodcS64D1SBmhTw04rBfVm8sy14Brmr3bTEbseCdzgibmNz7LYkieZtD1OPrCO2lrXMaWvDKTMpO6TUq72rLFTy+Fj1e3xArZb/76v2fs4HFp+g0p2N/gPfrgCl+UXAAA=\\\"]\\n\"}, {\"id\": \"36858672311232137356091439499594367794847255214593015820\", \"timestamp\": 1652800029017, \"message\": \"REPORT RequestId: 60d9a6a3-f31e-43e6-94a7-8485e06f8aa6\\tDuration: 13.98 ms\\tBilled Duration: 14 ms\\tMemory Size: 1024 MB\\tMax Memory Used: 87 MB\\tInit Duration: 584.39 ms\\t\\n\"}]}"
}
```

[^1]: Replace <your_xyz> elements with your content, for example: `"log_stream_name": "2022/05/17/[$LATEST]30dce751bc1a4e7497eb644171d70153"`.

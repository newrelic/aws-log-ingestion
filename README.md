# AWS - New Relic log ingestion

AWS Serverless Application that sends log data from CloudWatch Logs and S3 to New Relic Infrastructure - Cloud Integrations.

# Pre-requisites

- New Relic license key.

# Resources created by the SAM template

There are few resources that will be created when you create the application from the repository:

- The Lambda function itself
- A Role used to give execute permissions to the lambda function and to use the KMS key

# Configure region

If you are using New Relic's EU region, you will need to add this environment variable to your function:

```
NR_REGION: EU
```

# Configure Retries

You can configure the number of retries you want to perform in case the function fails to send the data in case of communication issues.

Please be aware that more number of retries can make the function run for longer time and therefore increases the probability of having higher costs for Lambda. On the contrary, decreasing the number of retries could increase the probility of data loss.

Recommended number is 3 retries, but you can change the retry behaviour by changing the below parameters: 

```python
MAX_RETRIES = 3  # Defines the number of retries after lambda failure to deliver data
INITIAL_BACKOFF = 1  # Defines the initial wait seconds until next retry is executed
BACKOFF_MULTIPLIER = 2  # Time multiplier between the retries 
```

As an example, in default above configuration, first retry will happen after 1 second, second retry after 2 seconds and third retry will happen after 4 seconds.


# Configure your New Relic License Key

After creating the function you will need to do the following to make the lambda function work properly:

- Select your function and open the 'Environment variables' section. You should see your license key assigned to the **LICENSE_KEY** environment variable, in clear text, if you opted to include it when deploying the function.
- If you initially ommited the license key, you will have to insert it now in the **LICENSE_KEY** environment variable.
- Go up and press *Save*.

Your function should now be working properly. You can go to the *Monitoring* tab and verify that *Invocation errors* should be 
zero or moving to zero. You can also see the logs by clicking in *View logs in CloudWatch*.
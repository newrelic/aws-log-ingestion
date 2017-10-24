# AWS - New Relic log ingestion

AWS Serverless Application that sends log data from CloudWatch Logs and S3 to New Relic Infrastructure - Cloud Integrations.

# Pre-requisites

- New Relic license key.
- KMS encryption key that will be used to encrypt/decrypt your New Relic license key (key ID, which is the last part of the ARN, will be needed when creating the application from the repository)

# Resources created by the SAM template

There are few resources that will be created when you create the application from the repository:

- The Lambda function itself
- A Role used to give execute permissions to the lambda function and to use the KMS key

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

- Select your function and open the 'Envronment variables' section. You should see your license key assigned to the **LICENSE_KEY** environment variable, in clear text.
- Open the *Encryption configuration* section and select *Enable helpers for encryption in transit*
- In *KMS key to encrypt in transit* select the **same** key as the one below in *KMS key to encrypt at rest*.
- Press the *Encrypt* button next to you license key.
- Go up and press *Save*.

Your function should now be working properly. You can go to the *Monitoring* tab and verify that *Invocation errors* should be 
zero or moving to zero. You can also see the logs by clicking in *View logs in CloudWatch*.
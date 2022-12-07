# Rampart Serverless

## Overview
A serverless componente for Rampart that exposes an interface for users to wrap core model serving logic into a function. Currently supports deploying a serverless FastAPI application on a local machine. Function invocations occur through HTTP Requests. 

## Implementation Details
### Example Function
The user function must only accept two arguments `context` and `event`. An `event` is custom request object containing attributes such as the request body. `context` is a context manager object that can be used for storing user data and access logging functionality. The function must return a `dict` object that will form the body of the response. Both the request and response must have `Content-Type` as `application/json`.
```python
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

def predict(context, event):
    body = event.body
    sent_str = body['sent_str']
    context.logger.info('Checking polarity')
    analyzer = SentimentIntensityAnalyzer()
    scores = analyzer.polarity_scores(sent_str)
    return scores

```
### Example Config File
```yaml
description: >
  Uses vaderSentiment package to predict sentiment scores for incoming request sentence.
functions:
  predict: # Endpoint for invoking the function
      handler: "sentiment_analyzer:predict" # Follows format of module_name:function_name
      method: "POST" # HTTP Method Type
```

## Deploying Component
### Using Docker
1. Copy the source files to `app` directory
2. Create a `requirements.txt` and `function_config.yaml` in root directory
3. Update Gunicorn configurations in `gunicorn_conf.py`
```shell
docker builld -t example_image .
docker run -d --name example_container -v PATH_TO_APP:/app -p 80:80 example_image
```
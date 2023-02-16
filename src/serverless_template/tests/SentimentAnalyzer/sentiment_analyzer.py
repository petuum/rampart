# Copyright 2023 Petuum, Inc. All Rights Reserved.

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer


def predict(context, event):
    body = event.body
    sent_str = body['sent_str']
    context.logger.info('Checking polarity')
    analyzer = SentimentIntensityAnalyzer()
    scores = analyzer.polarity_scores(sent_str)
    return scores


def respond(context, event):
    body = event.body
    sent_str = body['check_response']
    return {'response': sent_str}

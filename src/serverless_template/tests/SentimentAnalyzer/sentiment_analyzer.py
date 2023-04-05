# Copyright 2023 Petuum, Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License."

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

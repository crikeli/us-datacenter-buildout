"""
Starts the Step Functions pipeline execution (Glue clean -> crawl ->
Redshift COPY). Invoked either manually (aws lambda invoke, for the
one-time real run this project's data was produced with) or on the
EventBridge schedule defined in eventbridge.tf, for anyone who forks this
and wants it to re-run automatically when FracTracker republishes their
tracker.
"""

import json
import os

import boto3

sfn = boto3.client("stepfunctions")


def handler(event, context):
    response = sfn.start_execution(
        stateMachineArn=os.environ["STATE_MACHINE_ARN"],
        input=json.dumps({"triggered_by": event.get("source", "manual")}),
    )
    return {"executionArn": response["executionArn"]}

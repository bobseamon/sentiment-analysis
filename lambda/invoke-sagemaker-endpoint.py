import os
import json
import boto3
from botocore.exceptions import ClientError

# Get environment variables
TABLE_NAME = os.environ.get('DYNAMODB_TABLE_NAME')
MODEL_ID = os.environ.get('MODEL_ID')
TIMER_LAMBDA_ARN = os.environ.get('TIMER_LAMBDA_ARN') # ARN for the helper function

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
sagemaker_runtime = boto3.client('sagemaker-runtime')
lambda_client = boto3.client('lambda')
table = dynamodb.Table(TABLE_NAME)

def lambda_handler(event, context):
    """
    Acts as a proxy to invoke the SageMaker endpoint, with keep-alive logic.
    """
    try:
        print(f"Received event: {json.dumps(event)}")
        
        # --- 1. Get current state from DynamoDB ---
        response = table.get_item(Key={'modelId': MODEL_ID})
        item = response.get('Item', {})
        status = item.get('endpointStatus')
        endpoint_name = item.get('endpointName')
        schedule_name = item.get('scheduleName')

        if status != 'IN_SERVICE' or not endpoint_name:
            return api_gateway_response(404, {'error': 'Model is not currently running or available.'})

        # --- 2. "KEEP-ALIVE" LOGIC ---
        # If a schedule exists, invoke the helper function to extend its time.
        if schedule_name:
            print(f"Invoking timer extension for schedule: {schedule_name}")
            payload = {
                'schedule_name': schedule_name,
                'endpoint_arn': f"arn:aws:sagemaker:{os.environ['AWS_REGION']}:{context.invoked_function_arn.split(':')[4]}:endpoint/{endpoint_name}"
            }
            lambda_client.invoke(
                FunctionName=TIMER_LAMBDA_ARN,
                InvocationType='Event', # Fire and forget, no need to wait for response
                Payload=json.dumps(payload)
            )
        
        # --- 3. Invoke the SageMaker Endpoint (Original Logic) ---
        body = json.loads(event.get('body', '{}'))
        review_text = body.get('text')

        if not review_text:
            return api_gateway_response(400, {'error': 'Input text is required.'})

        payload_for_sagemaker = {"inputs": review_text}
        
        sagemaker_response = sagemaker_runtime.invoke_endpoint(
            EndpointName=endpoint_name,
            ContentType="application/json",
            Body=json.dumps(payload_for_sagemaker),
        )
        
        result = sagemaker_response["Body"].read().decode()
        print(f"Received successful prediction: {result}")
        return api_gateway_response(200, json.loads(result))

    except Exception as e:
        print(f"FATAL ERROR: {str(e)}")
        return api_gateway_response(500, {'error': 'An internal server error occurred.'})

def api_gateway_response(status_code, body_object):
    """Helper function to format the response for API Gateway"""
    return {
        'statusCode': status_code,
        'headers': {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Allow-Methods': 'OPTIONS,POST'
        },
        'body': json.dumps(body_object)
    }

import os
import json
import boto3
import time
from botocore.exceptions import ClientError

# Get environment variables
TABLE_NAME = os.environ.get('DYNAMODB_TABLE_NAME')
MODEL_ID = os.environ.get('MODEL_ID')
SAGEMAKER_MODEL_NAME = os.environ.get('SAGEMAKER_MODEL_NAME')
SAGEMAKER_ROLE_ARN = os.environ.get('SAGEMAKER_ROLE_ARN')
INSTANCE_TYPE = os.environ.get('INSTANCE_TYPE')

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
sagemaker_client = boto3.client('sagemaker')
table = dynamodb.Table(TABLE_NAME)

def lambda_handler(event, context):
    """
    Handles a request to start the SageMaker model endpoint.
    Manages state via DynamoDB to prevent race conditions and handle subscriptions.
    """
    try:
        # Parse user details from the incoming request body
        body = json.loads(event.get('body', '{}'))
        user_name = body.get('name')
        user_phone = body.get('phone')

        if not user_name or not user_phone:
            return api_gateway_response(400, {'error': 'Name and phone number are required.'})

        # Get the current state of our model from DynamoDB
        response = table.get_item(Key={'modelId': MODEL_ID})
        state = response.get('Item', {})
        status = state.get('endpointStatus', 'STOPPED')

        print(f"Current model status: {status}")
        
        # --- STATE MACHINE LOGIC ---

        if status == 'IN_SERVICE':
            print("Model is already running.")
            return api_gateway_response(200, {'message': 'Model is already running and ready for analysis.'})

        elif status == 'CREATING':
            print("Model is already creating. Adding user to subscriber list.")
            # Add this user to the list of subscribers to be notified
            table.update_item(
                Key={'modelId': MODEL_ID},
                UpdateExpression="SET subscribers = list_append(subscribers, :i)",
                ExpressionAttributeValues={':i': [{'name': user_name, 'phone': user_phone}]},
            )
            return api_gateway_response(200, {'message': 'Model is starting up. You will receive an SMS when it is ready.'})

        elif status == 'STOPPED':
            print("Model is stopped. Attempting to start deployment.")
            # Use a conditional update to prevent a race condition.
            # We only proceed if the status is still 'STOPPED'.
            try:
                table.update_item(
                    Key={'modelId': MODEL_ID},
                    UpdateExpression="SET endpointStatus = :new_status",
                    ConditionExpression="endpointStatus = :current_status",
                    ExpressionAttributeValues={
                        ':new_status': 'CREATING',
                        ':current_status': 'STOPPED'
                    }
                )
                
                # If the conditional update succeeded, this invocation "won the race"
                print("Successfully set status to CREATING. Starting endpoint deployment.")
                
                # Generate a unique name for the endpoint and its config
                timestamp = str(int(time.time()))
                endpoint_config_name = f'sentiment-model-config-{timestamp}'
                endpoint_name = f'sentiment-model-endpoint-{timestamp}'

                # 1. Create Endpoint Configuration
                sagemaker_client.create_endpoint_config(
                    EndpointConfigName=endpoint_config_name,
                    ProductionVariants=[{
                        'VariantName': 'AllTraffic',
                        'ModelName': SAGEMAKER_MODEL_NAME,
                        'InstanceType': INSTANCE_TYPE,
                        'InitialInstanceCount': 1
                    }]
                )
                
                # 2. Create the Endpoint
                sagemaker_client.create_endpoint(
                    EndpointName=endpoint_name,
                    EndpointConfigName=endpoint_config_name
                )
                
                # 3. Update DynamoDB with the new endpoint name and the first subscriber
                table.update_item(
                    Key={'modelId': MODEL_ID},
                    UpdateExpression="SET endpointName = :en, subscribers = :s",
                    ExpressionAttributeValues={
                        ':en': endpoint_name,
                        ':s': [{'name': user_name, 'phone': user_phone}]
                    }
                )
                
                return api_gateway_response(200, {'message': 'Model deployment started. You will receive an SMS when it is ready.'})

            except ClientError as e:
                # If the conditional check fails, another invocation "won the race"
                if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                    print("Lost race condition. Another process is starting the model. Subscribing user.")
                    # Add this user to the subscriber list created by the other process
                    table.update_item(
                        Key={'modelId': MODEL_ID},
                        UpdateExpression="SET subscribers = list_append(subscribers, :i)",
                        ExpressionAttributeValues={':i': [{'name': user_name, 'phone': user_phone}]},
                    )
                    return api_gateway_response(200, {'message': 'Model is starting up. You will receive an SMS when it is ready.'})
                else:
                    raise # Re-raise other errors
        else:
            # Handle other states like STOPPING if necessary
            return api_gateway_response(503, {'message': f'Model is in an unavailable state: {status}. Please try again later.'})

    except Exception as e:
        print(f"ERROR: {str(e)}")
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
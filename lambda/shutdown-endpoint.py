import os
import json
import boto3
from botocore.exceptions import ClientError

# Get environment variables
TABLE_NAME = os.environ.get('DYNAMODB_TABLE_NAME')
MODEL_ID = os.environ.get('MODEL_ID')

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
sagemaker_client = boto3.client('sagemaker')
table = dynamodb.Table(TABLE_NAME)

def lambda_handler(event, context):
    """
    Triggered by a one-time schedule from EventBridge Scheduler.
    Deletes the specified SageMaker endpoint and updates the state in DynamoDB.
    """
    try:
        print(f"Received event: {json.dumps(event)}")
        
        # The EventBridge schedule passes the endpoint name in the event payload
        endpoint_name = event.get('endpoint_name')
        
        if not endpoint_name:
            print("ERROR: No endpoint_name found in the event payload.")
            return {'statusCode': 400, 'body': 'Endpoint name not provided.'}
            
        print(f"Received shutdown request for endpoint: {endpoint_name}")

        # --- 1. Delete the SageMaker Endpoint ---
        try:
            sagemaker_client.delete_endpoint(EndpointName=endpoint_name)
            print(f"Successfully initiated deletion for endpoint: {endpoint_name}")
        except ClientError as e:
            # If the endpoint is already gone, that's okay.
            if e.response['Error']['Code'] == 'ValidationException':
                print(f"Endpoint {endpoint_name} not found. It may have already been deleted.")
            else:
                raise # Re-raise other errors
        
        # --- 2. Update DynamoDB State to STOPPED ---
        # This makes the system available for the next user.
        table.update_item(
            Key={'modelId': MODEL_ID},
            # Clear the endpointName AND the scheduleName
            UpdateExpression="SET endpointStatus = :status, endpointName = :name, scheduleName = :name",
            ExpressionAttributeValues={
                ':status': 'STOPPED',
                ':name': None 
            }
        )        
        print(f"Successfully updated DynamoDB status to STOPPED for modelId: {MODEL_ID}")

        return {'statusCode': 200, 'body': json.dumps('Shutdown process complete.')}

    except Exception as e:
        print(f"FATAL ERROR: {str(e)}")
        raise e

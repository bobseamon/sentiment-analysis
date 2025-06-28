import os
import json
import boto3
from datetime import datetime, timezone
from botocore.exceptions import ClientError

# Get environment variables
TABLE_NAME = os.environ.get('DYNAMODB_TABLE_NAME')
MODEL_ID = os.environ.get('MODEL_ID')
TIMER_LAMBDA_ARN = os.environ.get('TIMER_LAMBDA_ARN') # ARN of the new helper function

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
scheduler_client = boto3.client('scheduler')
lambda_client = boto3.client('lambda')
table = dynamodb.Table(TABLE_NAME)

def lambda_handler(event, context):
    """
    Checks the model status and extends the shutdown timer if it's about to expire.
    """
    try:
        response = table.get_item(Key={'modelId': MODEL_ID})
        item = response.get('Item', {})
        status = item.get('endpointStatus')
        schedule_name = item.get('scheduleName')
        endpoint_name = item.get('endpointName')
        
        is_running = (status == 'IN_SERVICE')
        
        # --- NEW TIMER EXTENSION LOGIC ---
        if is_running and schedule_name:
            try:
                schedule_details = scheduler_client.get_schedule(Name=schedule_name, GroupName='default')
                # The schedule expression is like 'at(2025-06-25T14:30:00)'
                schedule_str = schedule_details['ScheduleExpression'][3:-1] 
                scheduled_time = datetime.fromisoformat(schedule_str).replace(tzinfo=timezone.utc)
                time_now = datetime.now(timezone.utc)
                
                minutes_remaining = (scheduled_time - time_now).total_seconds() / 60
                
                print(f"Time until shutdown: {minutes_remaining:.2f} minutes.")

                # If less than 15 minutes remain, invoke the helper lambda to extend the timer
                if minutes_remaining < 15:
                    print("Shutdown time is less than 15 minutes away. Invoking timer extension.")
                    payload = {
                        'schedule_name': schedule_name,
                        'endpoint_arn': schedule_details['Target']['Arn'] # Pass the correct endpoint ARN
                    }
                    lambda_client.invoke(
                        FunctionName=TIMER_LAMBDA_ARN,
                        InvocationType='Event', # Fire and forget, we don't need to wait for the response
                        Payload=json.dumps(payload)
                    )
                    
            except ClientError as e:
                # This can happen if the schedule was just deleted. It's safe to ignore.
                print(f"Could not get schedule details for '{schedule_name}'. It may no longer exist. Error: {e}")

        return api_gateway_response(200, {'is_running': is_running})

    except Exception as e:
        print(f"ERROR: {str(e)}")
        return api_gateway_response(500, {'error': 'Could not retrieve model status.'})

def api_gateway_response(status_code, body_object):
    """Helper function to format the response for API Gateway"""
    return {
        'statusCode': status_code,
        'headers': {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Allow-Methods': 'OPTIONS,GET'
        },
        'body': json.dumps(body_object)
    }
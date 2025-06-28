import os
import json
import requests  # We will use the requests library to call the Textbelt API
from datetime import datetime, timedelta
import boto3

# Get environment variables
TABLE_NAME = os.environ.get('DYNAMODB_TABLE_NAME')
MODEL_ID = os.environ.get('MODEL_ID')
SHUTDOWN_LAMBDA_ARN = os.environ.get('SHUTDOWN_LAMBDA_ARN')
SCHEDULER_ROLE_ARN = os.environ.get('SCHEDULER_ROLE_ARN')
APP_URL = os.environ.get('APP_URL')
# We now get the Textbelt API key from an environment variable for security
TEXTBELT_API_KEY = os.environ.get('TEXTBELT_API_KEY') 

# Initialize AWS clients (we no longer need SNS client)
dynamodb = boto3.resource('dynamodb')
scheduler_client = boto3.client('scheduler')
table = dynamodb.Table(TABLE_NAME)

def lambda_handler(event, context):
    """
    Triggered by EventBridge when a SageMaker endpoint becomes IN_SERVICE.
    Notifies subscribed users via Textbelt and schedules the endpoint shutdown.
    """
    try:
        print(f"Received event: {json.dumps(event)}")
        
        endpoint_arn = event['resources'][0]
        endpoint_name = endpoint_arn.split('/')[-1]
        print(f"Endpoint {endpoint_name} is now IN_SERVICE.")

        # --- 1. Get User Info and update state ---
        table.update_item(
            Key={'modelId': MODEL_ID},
            UpdateExpression="SET endpointStatus = :status",
            ExpressionAttributeValues={':status': 'IN_SERVICE'}
        )
        
        response = table.get_item(Key={'modelId': MODEL_ID})
        item = response.get('Item', {})
        subscribers = item.get('subscribers', [])
        
        if not subscribers:
            print("No subscribers to notify.")
        else:
            print(f"Found {len(subscribers)} subscribers to notify.")
        
        # --- 2. Send SMS Notifications via Textbelt API ---
        for subscriber in subscribers:
            user_name = subscriber.get('name', 'there')
            user_phone = subscriber.get('phone')
            
            if user_phone:
                message = (
                    f"Hi {user_name}. Bob Seamon's sentiment analysis model is now "
                    f"available for use for the next 30 minutes "
                    f"here: {APP_URL}"
                )
                try:
                    # Make the POST request to the Textbelt API
                    textbelt_response = requests.post('https://textbelt.com/text', {
                        'phone': user_phone,
                        'message': message,
                        'key': TEXTBELT_API_KEY,
                    })
                    
                    # Log the response from Textbelt for debugging
                    print(f"Textbelt API response: {textbelt_response.json()}")

                    if textbelt_response.json().get("success"):
                        print(f"Successfully sent SMS to {user_phone} via Textbelt.")
                    else:
                        print(f"ERROR: Textbelt API indicated failure for {user_phone}.")

                except requests.exceptions.RequestException as e:
                    print(f"ERROR: Failed to call Textbelt API for {user_phone}. Reason: {str(e)}")

        # --- 3. Clean up the subscribers list ---
        table.update_item(
            Key={'modelId': MODEL_ID},
            UpdateExpression="SET subscribers = :empty_list",
            ExpressionAttributeValues={':empty_list': []}
        )
        print("Subscribers list has been cleared.")

        # --- 4. Schedule the 30-minute shutdown ---
        shutdown_time = datetime.utcnow() + timedelta(minutes=30)
        schedule_time_str = shutdown_time.strftime('%Y-%m-%dT%H:%M:%S')

        print(f"Scheduling shutdown for {schedule_time_str} UTC.")
        print(f"Scheduler details: ")
        print(f"Arn:  {SHUTDOWN_LAMBDA_ARN}")
        print(f"RoleArn: {SCHEDULER_ROLE_ARN}")
        print(f"Endpoint Name: {endpoint_name}")

        create_schedule_response = scheduler_client.create_schedule(
            Name=f'shutdown-schedule-{endpoint_name}',
            GroupName='default',
            ActionAfterCompletion='DELETE',
            ScheduleExpression=f'at({schedule_time_str})',
            FlexibleTimeWindow={'Mode': 'OFF'},
            Target={
                'Arn': SHUTDOWN_LAMBDA_ARN,
                'RoleArn': SCHEDULER_ROLE_ARN,
                'Input': json.dumps({'endpoint_name': endpoint_name})
            }
        )

        schedule_name = f'shutdown-schedule-{endpoint_name}'
        # Save the name of the schedule to our state machine
        table.update_item(
            Key={'modelId': MODEL_ID},
            UpdateExpression="SET scheduleName = :s_name",
            ExpressionAttributeValues={':s_name': schedule_name}
        )
        print(f"Saved schedule name {schedule_name} to DynamoDB.")

        schedule_arn = create_schedule_response.get('ScheduleArn') # Get the ARN
        print(f"Successfully created one-time shutdown schedule with ARN: {schedule_arn}")
            
        return {'statusCode': 200, 'body': json.dumps('Notification (via Textbelt) and shutdown scheduling complete.')}

    except Exception as e:
        print(f"FATAL ERROR: {str(e)}")
        raise e
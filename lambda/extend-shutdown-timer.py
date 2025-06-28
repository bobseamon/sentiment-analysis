import os
import json
import boto3
from datetime import datetime, timedelta
from botocore.exceptions import ClientError

# Initialize clients and get environment variables
scheduler_client = boto3.client('scheduler')
SHUTDOWN_LAMBDA_ARN = os.environ.get('SHUTDOWN_LAMBDA_ARN')
SCHEDULER_ROLE_ARN = os.environ.get('SCHEDULER_ROLE_ARN')

def lambda_handler(event, context):
    """
    This is a helper function. It receives a schedule_name and endpoint_info,
    and extends the schedule by 30 minutes from now.
    """
    schedule_name = event.get('schedule_name')
    endpoint_arn = event.get('endpoint_arn')
    endpoint_name = endpoint_arn.split('/')[-1]

    if not all([schedule_name, endpoint_arn]):
        print("ERROR: schedule_name and endpoint_arn are required.")
        return {'status': 'error', 'message': 'Missing required parameters.'}

    try:
        print(f"Attempting to extend schedule: {schedule_name}")
        new_shutdown_time = datetime.utcnow() + timedelta(minutes=30)
        new_schedule_time_str = new_shutdown_time.strftime('%Y-%m-%dT%H:%M:%S')

        scheduler_client.update_schedule(
            Name=schedule_name,
            GroupName='default',
            ActionAfterCompletion='DELETE',
            ScheduleExpression=f'at({new_schedule_time_str})',
            FlexibleTimeWindow={'Mode': 'OFF'},
            Target={
                'Arn': SHUTDOWN_LAMBDA_ARN,
                'RoleArn': SCHEDULER_ROLE_ARN,
                'Input': json.dumps({'endpoint_name': endpoint_name})
            }
        )
        print(f"Successfully extended schedule {schedule_name} to {new_schedule_time_str} UTC.")
        return {'status': 'success', 'message': f'Schedule extended to {new_schedule_time_str} UTC.'}

    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceNotFoundException':
            print(f"Schedule {schedule_name} not found. It may have already executed.")
            return {'status': 'not_found', 'message': 'Schedule not found.'}
        else:
            print(f"ERROR updating schedule: {str(e)}")
            raise e
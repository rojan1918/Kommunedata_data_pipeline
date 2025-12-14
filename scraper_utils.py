import os
import boto3
import datetime
from botocore.exceptions import ClientError

# --- CONFIGURATION ---
IS_RENDER = os.environ.get('RENDER') == 'true'
WASABI_ACCESS_KEY = os.environ.get("WASABI_ACCESS_KEY")
WASABI_SECRET_KEY = os.environ.get("WASABI_SECRET_KEY")
WASABI_ENDPOINT = os.environ.get("WASABI_ENDPOINT", "https://s3.eu-central-1.wasabisys.com")
SCRAPE_MODE = os.environ.get("SCRAPE_MODE", "ALL")  # 'ALL' or 'NEW'

def get_s3_client():
    if not WASABI_ACCESS_KEY or not WASABI_SECRET_KEY:
        print("   > Error: Wasabi credentials missing.")
        return None
    
    return boto3.client(
        's3',
        endpoint_url=WASABI_ENDPOINT,
        aws_access_key_id=WASABI_ACCESS_KEY,
        aws_secret_access_key=WASABI_SECRET_KEY
    )

def ensure_bucket_exists(s3_client, bucket_name):
    """Creates the bucket if it does not exist."""
    if not s3_client: return False
    
    try:
        s3_client.head_bucket(Bucket=bucket_name)
        # print(f"   > Bucket '{bucket_name}' exists.")
        return True
    except ClientError as e:
        error_code = int(e.response['Error']['Code'])
        if error_code == 404:
            print(f"   > Bucket '{bucket_name}' not found. Creating...")
            try:
                s3_client.create_bucket(Bucket=bucket_name)
                print(f"   > Bucket '{bucket_name}' created successfully.")
                return True
            except Exception as create_err:
                print(f"   > Failed to create bucket '{bucket_name}': {create_err}")
                return False
        else:
            print(f"   > Error checking bucket '{bucket_name}': {e}")
            return False

def upload_to_wasabi(local_file_path, bucket_name, remote_filename):
    s3 = get_s3_client()
    if not s3: return False

    # Ensure bucket exists before uploading
    ensure_bucket_exists(s3, bucket_name)

    try:
        try:
            s3.head_object(Bucket=bucket_name, Key=remote_filename)
            print(f"   > Skipping: {remote_filename} already exists in cloud.")
            return "EXISTS"
        except:
            pass

        print(f"   > Uploading to {bucket_name}...")
        with open(local_file_path, "rb") as f:
            s3.put_object(Bucket=bucket_name, Key=remote_filename, Body=f)
        print(f"   > Upload Success!")
        return True
    except Exception as e:
        print(f"   > Wasabi Upload Error: {e}")
        return False

def should_scrape(date_obj):
    """
    Returns True if we should scrape based on SCRAPE_MODE.
    date_obj: datetime.date object of the meeting.
    """
    if SCRAPE_MODE == "ALL":
        return True
    
    if SCRAPE_MODE == "NEW":
        today = datetime.date.today()
        # If the meeting is today or in the future, scrape it.
        if date_obj >= today:
            return True
        return False
    
    return True

def get_download_limit():
    """Returns integer limit or None if no limit."""
    limit = os.environ.get("DOWNLOAD_LIMIT")
    if limit and limit.lower() not in ['none', 'null', '']:
        try:
            return int(limit)
        except ValueError:
            return None
    return None


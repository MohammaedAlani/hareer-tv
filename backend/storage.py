"""Private S3 storage; the app receives stable gateway URLs, never S3 credentials."""
import os
from urllib.parse import urlsplit

REQUIRED = ('S3_ENDPOINT_URL','S3_BUCKET','S3_ACCESS_KEY_ID','S3_SECRET_ACCESS_KEY','PUBLIC_BASE_URL')

def configured():
    return all(os.environ.get(key, '').strip() for key in REQUIRED)

class Storage:
    def __init__(self):
        import boto3
        from botocore.config import Config
        self.base_url = os.environ['PUBLIC_BASE_URL'].rstrip('/')
        endpoint = os.environ['S3_ENDPOINT_URL']
        for value in (self.base_url, endpoint):
            parsed = urlsplit(value)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError('Storage and public URLs must use HTTPS without credentials or query strings')
        if len(self.base_url)>500: raise ValueError('Public URL is too long')
        self.bucket = os.environ['S3_BUCKET']
        self.client = boto3.client('s3',endpoint_url=endpoint,
            region_name=os.environ.get('S3_REGION','auto'),
            aws_access_key_id=os.environ['S3_ACCESS_KEY_ID'],
            aws_secret_access_key=os.environ['S3_SECRET_ACCESS_KEY'],
            config=Config(signature_version='s3v4',s3={'addressing_style':'path'},
                request_checksum_calculation='when_required',response_checksum_validation='when_required',
                connect_timeout=10,read_timeout=60,retries={'max_attempts':3}))

    def upload(self, path, key, content_type):
        from boto3.s3.transfer import TransferConfig
        self.client.upload_file(str(path),self.bucket,key,
            ExtraArgs={'ContentType':content_type},
            Config=TransferConfig(use_threads=False))
        # Publish only once object storage confirms the exact expected size.
        stored = self.client.head_object(Bucket=self.bucket,Key=key)
        if stored['ContentLength'] != path.stat().st_size:
            raise RuntimeError('Stored object size did not match')

    def signed_url(self, key):
        return self.client.generate_presigned_url('get_object',Params={'Bucket':self.bucket,'Key':key},ExpiresIn=900)

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

@unittest.skipUnless(importlib.util.find_spec('boto3'), 'boto3 not installed')
class StorageTests(unittest.TestCase):
    def test_private_upload_and_signed_playback(self):
        from backend.storage import Storage
        from botocore.stub import Stubber
        with patch.dict(os.environ,{'S3_ENDPOINT_URL':'https://objects.example','S3_BUCKET':'test-bucket','S3_ACCESS_KEY_ID':'test-key','S3_SECRET_ACCESS_KEY':'test-secret','PUBLIC_BASE_URL':'https://tv.example','S3_REGION':'auto'}):
            storage=Storage()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.mp4';path.write_bytes(b'video')
            with patch.object(storage.client,'upload_file') as upload, Stubber(storage.client) as stub:
                stub.add_response('head_object',{'ContentLength':5},{'Bucket':'test-bucket','Key':'hareer-tv/imports/1/video.mp4'})
                storage.upload(path,'hareer-tv/imports/1/video.mp4','video/mp4')
                self.assertEqual(upload.call_args.kwargs['ExtraArgs'],{'ContentType':'video/mp4'})
        url=storage.signed_url('hareer-tv/imports/1/video.mp4')
        self.assertTrue(url.startswith('https://objects.example/test-bucket/hareer-tv/imports/1/video.mp4?'))
        self.assertIn('X-Amz-Expires=900',url)
    def test_bad_public_origin_rejected(self):
        from backend.storage import Storage
        with patch.dict(os.environ,{'S3_ENDPOINT_URL':'https://objects.example','PUBLIC_BASE_URL':'http://tv.example'}):
            with self.assertRaises(ValueError): Storage()

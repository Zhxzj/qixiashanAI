"""Credential privacy tests use synthetic values only, with no external requests."""
import json,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import config
from app.services import page_credentials as keys

class CredentialStorageTests(unittest.TestCase):
    def test_legacy_key_is_removed_not_loaded(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';path.write_text(json.dumps({'deepseek_api_key':'synthetic-legacy-only','model':'deepseek-flash'}))
            with patch.object(config,'CONFIG_PATH',path):
                result=config.load_config()
            self.assertEqual(result['deepseek_api_key'],'')
            self.assertNotIn('synthetic-legacy-only',path.read_text())

    def test_any_config_write_strips_key(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json'
            with patch.object(config,'CONFIG_PATH',path):config.save_config({'deepseek_api_key':'synthetic-never-persist'})
            self.assertEqual(json.loads(path.read_text())['deepseek_api_key'],'')

class PageCredentialAPITests(unittest.TestCase):
    def setUp(self):
        import app.main as main
        self.main=main;self.client=TestClient(main.app,base_url='http://127.0.0.1');self.client.__enter__()
        self.page=str(uuid.uuid4());self.other=str(uuid.uuid4());self.headers={'X-Qixi-Page':self.page}
        self.previous_tasks=set(main.recap_tasks)
    def tearDown(self):
        keys.forget(self.page);keys.forget(self.other)
        # Each TestClient owns a different loop; discard this test's completed fixtures.
        for name in set(self.main.recap_tasks)-self.previous_tasks:self.main.recap_tasks.pop(name)
        self.client.__exit__(None,None,None)
    def enable(self,value='synthetic-page-only'):
        return self.client.post('/api/config',headers=self.headers,json={'deepseek_api_key':value})
    def test_pages_are_isolated_and_no_key_in_response(self):
        response=self.enable();self.assertEqual(response.status_code,200);self.assertNotIn('synthetic-page-only',response.text)
        self.assertTrue(self.client.get('/api/health',headers=self.headers).json()['key_configured'])
        self.assertFalse(self.client.get('/api/health',headers={'X-Qixi-Page':self.other}).json()['key_configured'])
        self.assertFalse(self.client.get('/api/health').json()['key_configured'])
        self.assertEqual(dict(self.main.cfg)['deepseek_api_key'],'')
    def test_forget_and_missing_capability(self):
        self.assertEqual(self.client.post('/api/config',json={'deepseek_api_key':'synthetic'}).status_code,400)
        self.enable();self.client.post('/api/config/forget',json={'page_id':self.page})
        self.assertFalse(self.client.get('/api/health',headers=self.headers).json()['key_configured'])
    def test_validation_does_not_echo_secret(self):
        value='synthetic-sensitive-'+('x'*600)
        response=self.enable(value);self.assertEqual(response.status_code,422);self.assertNotIn(value,response.text)
    def test_request_context_reaches_stream_and_background_task(self):
        self.enable();captured=[]
        async def fake_stream(*args,**kwargs):
            captured.append(self.main.cfg['deepseek_api_key'])
            yield {'type':'delta','text':'synthetic response'}
        async def fake_recap(*args):
            captured.append(self.main.cfg.get('deepseek_api_key'))
            return {'diary':{},'visited':[]}
        with patch.object(self.main.agent,'stream',fake_stream):
            self.client.post('/api/chat',headers=self.headers,json={'session_id':'key-test-'+uuid.uuid4().hex,'text':'test'})
        with patch.object(self.main,'make_recap',fake_recap):
            response=self.client.post('/api/recap',headers=self.headers,json={'session_id':'key-test-'+uuid.uuid4().hex,'photos':[]})
            self.assertEqual(response.status_code,200)
        self.assertEqual(captured,['synthetic-page-only','synthetic-page-only'])
    def test_model_test_only_uses_expected_provider(self):
        self.enable();captured=[]
        async def fake_post(url,**kwargs):
            captured.append((url,kwargs['headers']['Authorization']))
            class Response:status_code=200
            return Response()
        with patch.object(self.main.provider.chat,'post',fake_post):
            response=self.client.post('/api/config/test',headers=self.headers)
        self.assertTrue(response.json()['ok']);self.assertEqual(captured,[('https://api.deepseek.com/chat/completions','Bearer synthetic-page-only')])

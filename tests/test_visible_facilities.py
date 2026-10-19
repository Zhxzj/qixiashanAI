import math
import json
from pathlib import Path
import unittest
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]


class VisibleFacilitiesTests(unittest.TestCase):
    def test_only_approved_yellow_gates_and_unnumbered_toilets(self):
        data=json.loads((ROOT/'app/data/map_annotations.json').read_text(encoding='utf-8'))
        gates=[p for p in data['items'] if p['category']=='gate' and p['coord']]
        self.assertEqual(len(gates),2)
        self.assertEqual(len(data['items']),14)
        self.assertTrue(all(p['name']=='公共厕所' for p in data['items'] if p['category']=='toilet'))
        params=data['registration']['parameters']
        for p in gates:
            self.assertEqual(p['name'],'大门')
            self.assertEqual(p['source']['kind'],'user_yellow_screenshot')
            x,y=p['source']['pixel_center']
            self.assertEqual(p['coord'],[round(math.degrees(math.atan(math.sinh(math.radians((y-params['by'])/params['ay'])))),7),round((x-params['bx'])/params['ax'],7)])

    def test_html_assets_and_version_contract_are_consistent(self):
        from app.main import app
        client=TestClient(app,base_url='http://127.0.0.1')
        version=client.get('/api/ui-version').json()
        page=client.get('/')
        self.assertEqual(page.headers['cache-control'],'no-store')
        self.assertIn(version['web_revision'],page.text)
        self.assertIn(version['build_id'],page.text)
        self.assertNotIn('__UI_INFO__',page.text)
        self.assertNotIn('__WEB_REVISION__',page.text)
        self.assertEqual(client.get('/js/map-osm.js').headers['cache-control'],'no-store')
        for removed in ['viewAllToilets','viewAllFacilities','facilityVisibility','mapStatus','showPublicToilets']:
            self.assertNotIn(removed,page.text)
        self.assertFalse(any(p['category']=='toilet_candidate' for p in client.get('/api/map/osm/data').json()['pois']))

    def test_approved_gate_navigation_uses_real_graph_endpoint(self):
        import time
        import app.main as main
        client=TestClient(main.app,base_url='http://127.0.0.1')
        for p in main.services['annotations'].snapshot()['items']:
            if p['category']!='gate':continue
            sid='gate-route-'+p['id']
            session={'session_id':sid,'generation':main.sessions.get(sid)['generation']}
            self.assertEqual(client.post('/api/map/mode',json={**session,'mode':'real','provider':'osm'}).status_code,200)
            origin=main.services['osm'].resolve('千佛岩')['coord']
            response=client.post('/api/map/osm/plan',json={**session,'origin':origin,'destination':p['coord'],'sequence':int(time.time()*10000),'annotation_targets':[{'id':p['id'],'role':'destination','position_revision':p['position_revision']}]})
            self.assertEqual(response.status_code,200,response.text)
            route=response.json();target=route['annotation_targets'][0]
            self.assertEqual(target['road_endpoint'],route['geometry'][-1])
            self.assertEqual(target['coord'],p['coord'])
            self.assertFalse(target['access_verified'])
            token=client.post('/api/map/location/start',json=session).json()['token']
            lat,lng=route['geometry'][-1]
            sample=client.post('/api/map/location',json={**session,'token':token,'sequence':1,'lat':lat,'lng':lng,'raw_wgs84':[lat,lng],'coordinate_system':'WGS84','accuracy_m':5,'sample_at':time.time()})
            self.assertEqual(sample.status_code,200,sample.text)
            state=client.get('/api/state',params={'session_id':sid}).json()
            self.assertEqual(state['navigation']['status'],'road_endpoint_nearby')
            self.assertIsNone(state['arrived'])


if __name__=='__main__':unittest.main()

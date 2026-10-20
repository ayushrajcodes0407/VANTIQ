import unittest
import json
import os
import sys

# Import our Flask app
from app import app, BASE_DIR

class JarvisFullTestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.testing = True
        cls.client = app.test_client()

    def test_01_index_html(self):
        """Test that the main HUD interface is served with 200 OK"""
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'J.A.R.V.I.S.', res.data)
        self.assertIn(b'STARK INDUSTRIES', res.data)
        print("[PASS] Index HTML dashboard served successfully.")

    def test_02_status_endpoint(self):
        """Test /api/status telemetry"""
        res = self.client.get('/api/status')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "ONLINE")
        self.assertIn("cpu", data)
        self.assertIn("ram", data)
        self.assertIn("time", data)
        self.assertIn("date", data)
        print(f"[PASS] Status endpoint returned: Status={data['status']}, Time={data['time']}, CPU={data['cpu']}%")

    def test_03_system_endpoint(self):
        """Test /api/system hardware metrics"""
        res = self.client.get('/api/system')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("cpu_percent", data)
        self.assertIn("ram_used_gb", data)
        print(f"[PASS] System metrics: CPU={data['cpu_percent']}%, RAM={data['ram_used_gb']}GB / {data['ram_total_gb']}GB")

    def test_04_joke_endpoint(self):
        """Test /api/joke pyjokes integration"""
        res = self.client.get('/api/joke')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(len(data.get("joke", "")) > 5)
        print(f"[PASS] Joke protocol: \"{data['joke'][:40]}...\"")

    def test_05_wikipedia_endpoint(self):
        """Test /api/wikipedia knowledge retrieval"""
        res = self.client.get('/api/wikipedia?query=Python+(programming+language)')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("summary", data)
        print(f"[PASS] Wikipedia summary retrieved ({len(data['summary'])} chars)")

    def test_06_covid_endpoint(self):
        """Test /api/covid stats mapping"""
        res = self.client.get('/api/covid?state=maharashtra')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("state"), "Maharashtra")
        self.assertIn("active", data)
        print(f"[PASS] COVID metrics for Maharashtra: Active={data['active']}")

    def test_07_contacts_endpoint(self):
        """Test /api/contacts list and retrieval"""
        res = self.client.get('/api/contacts')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("contacts", data)
        self.assertGreaterEqual(data.get("total", 0), 1)
        print(f"[PASS] Contacts database verified ({data['total']} contacts found)")

    def test_08_qrcode_generation(self):
        """Test /api/qrcode matrix synthesizer"""
        res = self.client.post('/api/qrcode', 
                               data=json.dumps({"text": "https://github.com/BolisettySujith/J.A.R.V.I.S"}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")
        self.assertTrue(os.path.exists(os.path.join(BASE_DIR, 'QrCodes', data['filename'])))
        print(f"[PASS] QR code synthesized successfully: {data['filename']}")

    def test_09_news_endpoint(self):
        """Test /api/news headlines retrieval"""
        res = self.client.get('/api/news')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("articles", data)
        self.assertGreater(len(data["articles"]), 0)
        print(f"[PASS] News protocol verified ({len(data['articles'])} articles)")

    def test_10_command_processor(self):
        """Test /api/command routing (Jokes, Time, System, YouTube)"""
        # Test time command
        res_time = self.client.post('/api/command', data=json.dumps({"command": "what is the time"}), content_type='application/json')
        self.assertEqual(res_time.status_code, 200)
        self.assertEqual(res_time.get_json().get("action"), "time")

        # Test joke command
        res_joke = self.client.post('/api/command', data=json.dumps({"command": "tell me a joke"}), content_type='application/json')
        self.assertEqual(res_joke.status_code, 200)
        self.assertEqual(res_joke.get_json().get("action"), "joke")

        # Test system command
        res_sys = self.client.post('/api/command', data=json.dumps({"command": "check system cpu"}), content_type='application/json')
        self.assertEqual(res_sys.status_code, 200)
        self.assertEqual(res_sys.get_json().get("action"), "system")
        
        print("[PASS] Command processor routed commands (time, joke, system) accurately.")

    def test_11_ui_asset_delivery(self):
        """Test that HUD gifs and images are accessible"""
        res1 = self.client.get('/UI/ironman1.gif')
        self.assertEqual(res1.status_code, 200)
        res2 = self.client.get('/UI/powersource.gif')
        self.assertEqual(res2.status_code, 200)
        res3 = self.client.get('/UI/ringJar.gif')
        self.assertEqual(res3.status_code, 200)
        print("[PASS] All Iron Man HUD UI assets verified and loading (ironman1, powersource, ringJar).")

if __name__ == '__main__':
    print("==================================================")
    print(" Running Complete J.A.R.V.I.S. Verification Suite")
    print("==================================================")
    unittest.main(verbosity=2)

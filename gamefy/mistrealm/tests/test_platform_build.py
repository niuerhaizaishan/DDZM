"""Platform build preserves legacy assets and installs the SDK-safe version selector."""
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT=Path(__file__).resolve().parents[3]

class PlatformBuild(unittest.TestCase):
    def test_gateway_build_removes_origin_from_all_published_text(self):
        with TemporaryDirectory() as directory:
            subprocess.run([sys.executable,str(ROOT/'scripts/build_mistrealm_platform.py'),directory,
                            '--api-base','https://gateway.example'],check=True)
            out=Path(directory)/'publish'
            for name in ['config.js','classic/config.js','v3/config.js','v3-original/config.js','v3-r1/config.js']:
                self.assertIn('https://gateway.example',(out/name).read_text())
            for path in out.rglob('*'):
                if path.suffix in ['.js','.json','.html','.css']:
                    self.assertNotIn('49.234.20.159',path.read_text(),str(path))

    def test_plaintext_gateway_rejected_before_build(self):
        with TemporaryDirectory() as directory:
            result=subprocess.run([sys.executable,str(ROOT/'scripts/build_mistrealm_platform.py'),directory,
                                   '--api-base','http://gateway.example'],capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse((Path(directory)/'publish').exists())

    def test_isolated_publish_build(self):
        with TemporaryDirectory() as directory:
            subprocess.run([sys.executable,str(ROOT/'scripts/build_mistrealm_platform.py'),directory],check=True)
            out=Path(directory)/'publish';source=ROOT/'gamefy/mistrealm/publish'
            self.assertEqual((out/'legacy.html').read_bytes(),(source/'index.html').read_bytes())
            self.assertIn('./entry.js',(out/'index.html').read_text())
            self.assertTrue((out/'entry.js').exists())
            for name in ['config.js','classic/config.js','v3/config.js','v3-original/config.js','v3-r1/config.js']:
                self.assertIn('https://49.234.20.159',(out/name).read_text())
            self.assertEqual(len(list((out/'assets/classic').glob('*.webp'))),122)
            self.assertEqual(len(list((out/'assets/expedition').glob('*.webp'))),60)
            self.assertIn("apiBase:''",(source/'classic/config.js').read_text())
            self.assertIn("apiBase:''",(source/'v3/config.js').read_text())
            self.assertTrue((out/'v3-original/cards.json').exists())
            self.assertIn('originalV3?',(out/'entry.js').read_text())
            self.assertIn('let version=3',(out/'entry.js').read_text())

if __name__=='__main__':unittest.main()

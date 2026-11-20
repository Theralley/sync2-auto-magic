"""Pure readiness and reused SHA tests; no CE execution."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class Pure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=(ROOT/'s2am/native/s2amloadctl.c').read_text()
        pure=source.split('/* load pure begin */',1)[1].split('/* load pure end */',1)[0]
        cls.folder=Path(tempfile.mkdtemp()); cls.program=cls.folder/'pure'
        code='''#include <stdint.h>\n#include <stdio.h>\n#include <string.h>\n#include <stdlib.h>\ntypedef uint32_t DWORD;typedef uint8_t BYTE;\n#include "load_sha256.h"\n'''+pure+'''
int main(int argc,char**argv){if(argc!=3)return 2;
if(!strcmp(argv[1],"ready")){printf("%d\\n",header_ready((const BYTE*)argv[2],(DWORD)strlen(argv[2]),42,7));return 0;}
if(!strcmp(argv[1],"sha")){Sha256 s;BYTE out[32];unsigned i;sha256_init(&s);sha256_update(&s,(const BYTE*)argv[2],(DWORD)strlen(argv[2]));sha256_final(&s,out);for(i=0;i<32;i++)printf("%02x",out[i]);puts("");return 0;}return 2;}
'''
        (cls.folder/'pure.c').write_text(code)
        p=subprocess.run(['clang','-std=c99','-Wall','-Wextra','-Werror','-I',str(ROOT/'s2am/native'),str(cls.folder/'pure.c'),'-o',str(cls.program)],capture_output=True,text=True)
        if p.returncode: raise AssertionError(p.stderr)

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.folder)

    def run_pure(self,mode,text):
        return subprocess.check_output([str(self.program),mode,text],text=True).strip()

    def test_readiness_is_bound_to_child_and_canonical_positive_frequency(self):
        prefix='S2AM-LOAD,1\r\nmeta,60,5000,512,256,42,7\r\nfrequency,start,'
        for freq,expected in [('8000000',1),('0',0),('08000000',0),('1000000001',0),('999999999999999999',0)]:
            self.assertEqual(self.run_pure('ready',prefix+freq+'\r\n'),str(expected))
        self.assertEqual(self.run_pure('ready',prefix.replace(',42,7',',43,7')+'8000000\r\n'),'0')
        self.assertEqual(self.run_pure('ready',prefix+'8000000'),'0')

    def test_readiness_truncated_prefixes_are_not_success(self):
        text='S2AM-LOAD,1\r\nmeta,60,5000,512,256,42,7\r\nfrequency,start,8000000\r\n'
        for i in range(len(text)):
            self.assertEqual(self.run_pure('ready',text[:i]),'0')

    def test_reused_sha_matches_known_vectors(self):
        for text in ('','abc','x'*1025):
            self.assertEqual(self.run_pure('sha',text),hashlib.sha256(text.encode()).hexdigest())

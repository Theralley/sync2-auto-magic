"""Isolated build orchestration tests; no Docker or server calls."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from tools import build_load_observer as build


class Build(unittest.TestCase):
    def test_refuses_mac_before_creating_output(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(build.sys,"platform","darwin"):
            out=Path(d)/"new"
            with self.assertRaises(RuntimeError):
                build.build(Path(d),out)
            self.assertFalse(out.exists())

    def test_server_build_binds_sources_and_artifacts(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); source=p/"source"; source.mkdir()
            for name in build.SOURCES:
                (source/name).write_text("fixture "+name)
            out=p/"out"
            def run(cmd,**kw):
                if "arm-mingw32ce-gcc" in cmd:
                    (out/"S2AMLOAD.EXE").write_bytes(b"synthetic executable")
                if "arm-mingw32ce-objdump" in cmd:
                    kw["stdout"].write(b"synthetic disassembly")
            with mock.patch.object(build.sys,"platform","linux"), \
                 mock.patch.object(build.socket,"gethostname",return_value="ant-srv-001"), \
                 mock.patch.object(build.container,"docker",return_value=["docker"]), \
                 mock.patch.object(build.subprocess,"run",side_effect=run) as call, \
                 mock.patch.object(build.native,"check"):
                build.build(source,out)
            result=json.loads((out/"result.json").read_text())
            self.assertEqual(result["state"],"complete")
            self.assertIn("S2AMLOAD.EXE",result["binaries"])
            self.assertEqual(len(result["sources"]),2)
            for args in call.call_args_list:
                self.assertIn("--network",args.args[0])
                self.assertIn("none",args.args[0])

    def test_failed_build_retains_durable_failed_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); source=p/"source"; source.mkdir()
            for name in build.SOURCES:
                (source/name).write_text("fixture")
            out=p/"out"
            with mock.patch.object(build.sys,"platform","linux"), \
                 mock.patch.object(build.socket,"gethostname",return_value="ant-srv-001"), \
                 mock.patch.object(build.container,"docker",return_value=["docker"]), \
                 mock.patch.object(build.subprocess,"run",side_effect=RuntimeError("failed")):
                with self.assertRaises(RuntimeError):
                    build.build(source,out)
            self.assertEqual(json.loads((out/"result.json").read_text())["state"],"failed")
            self.assertTrue((out/"dispatch.json").exists())
            self.assertFalse((out/"manifest.json").exists())

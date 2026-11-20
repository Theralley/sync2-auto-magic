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
                    (out/cmd[cmd.index("-o")+1]).write_bytes(b"synthetic executable")
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
            self.assertEqual(len(result["sources"]),4)
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

    def test_oversized_compiler_output_is_rejected_before_pe_parser(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); source=p/"source"; source.mkdir()
            for name in build.SOURCES:
                (source/name).write_text("fixture")
            out=p/"out"
            def run(cmd,**kw):
                if "arm-mingw32ce-gcc" in cmd:
                    (out/"S2AMLOAD.EXE").write_bytes(b"x"*(1024*1024+1))
            with mock.patch.object(build.sys,"platform","linux"), \
                 mock.patch.object(build.socket,"gethostname",return_value="ant-srv-001"), \
                 mock.patch.object(build.container,"docker",return_value=["docker"]), \
                 mock.patch.object(build.subprocess,"run",side_effect=run), \
                 mock.patch.object(build.native,"check") as check:
                with self.assertRaises(ValueError):
                    build.build(source,out)
                self.assertEqual(check.call_count,0)
            self.assertEqual(json.loads((out/"result.json").read_text())["state"],"failed")
            self.assertFalse((out/"manifest.json").exists())

    def test_checked_reads_reject_nonregular_paths_without_blocking(self):
        import os
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); regular=p/"regular"; regular.write_bytes(b"ok")
            link=p/"link"; link.symlink_to(regular)
            fifo=p/"fifo"; os.mkfifo(fifo)
            self.assertEqual(build.checked_read(regular),b"ok")
            for target in (link,fifo,p):
                with self.subTest(target=target.name),self.assertRaises((OSError,ValueError)):
                    build.checked_read(target)

    def test_explicit_actions_route_requires_own_build_branch(self):
        good={"GITHUB_ACTIONS":"true","GITHUB_REPOSITORY":"Theralley/sync2-auto-magic",
              "GITHUB_REF":"refs/heads/build/raw-load-20261120","GITHUB_EVENT_NAME":"push",
              "GITHUB_SHA":"a"*40,"GITHUB_RUN_ID":"123","GITHUB_RUN_ATTEMPT":"1"}
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/"source";source.mkdir()
            for name in build.SOURCES: (source/name).write_text("fixture")
            out=Path(d)/"out"
            def run(cmd,**kw):
                if "arm-mingw32ce-gcc" in cmd: (out/cmd[cmd.index("-o")+1]).write_bytes(b"synthetic executable")
                if "arm-mingw32ce-objdump" in cmd: kw["stdout"].write(b"synthetic disassembly")
            with mock.patch.object(build.sys,"platform","linux"), \
                 mock.patch.object(build.socket,"gethostname",return_value="github-runner"), \
                 mock.patch.dict(build.os.environ,good,clear=True), \
                 mock.patch.object(build.container,"docker",return_value=["docker"]), \
                 mock.patch.object(build.subprocess,"run",side_effect=run), \
                 mock.patch.object(build.native,"check"):
                result=build.build(source,out,github_actions=True)
            self.assertEqual(result["build_host"],"github-actions")
            self.assertEqual(result["ci"]["sha"],"a"*40)
            self.assertEqual(result["ci"]["run_attempt"],"1")

    def test_actions_route_refuses_wrong_repo_main_and_nonlinux(self):
        good={"GITHUB_ACTIONS":"true","GITHUB_REPOSITORY":"Theralley/sync2-auto-magic",
              "GITHUB_REF":"refs/heads/build/raw-load-20261120","GITHUB_EVENT_NAME":"push",
              "GITHUB_SHA":"a"*40,"GITHUB_RUN_ID":"123","GITHUB_RUN_ATTEMPT":"1"}
        variants=[("linux",{"GITHUB_REPOSITORY":"vendor/other"}),
                  ("linux",{"GITHUB_REF":"refs/heads/main"}),
                  ("linux",{"GITHUB_ACTIONS":"false"}),
                  ("linux",{"GITHUB_EVENT_NAME":"pull_request"}),
                  ("linux",{"GITHUB_RUN_ATTEMPT":"0"}),
                  ("darwin",{})]
        for platform,change in variants:
            with self.subTest(platform=platform,change=change),tempfile.TemporaryDirectory() as d, \
                 mock.patch.object(build.sys,"platform",platform), \
                 mock.patch.object(build.socket,"gethostname",return_value="github-runner"), \
                 mock.patch.dict(build.os.environ,{**good,**change},clear=True):
                out=Path(d)/"out"
                with self.assertRaises(RuntimeError): build.build(Path(d),out,github_actions=True)
                self.assertFalse(out.exists())

    def test_controller_compilation_is_bound_to_new_payload(self):
        import hashlib
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); source=p/"source"; source.mkdir()
            for name in build.SOURCES: (source/name).write_text("fixture "+name)
            out=p/"out"; commands=[]
            def run(cmd,**kw):
                commands.append(cmd)
                if "arm-mingw32ce-gcc" in cmd:
                    name=cmd[cmd.index("-o")+1]
                    (out/name).write_bytes(b"synthetic "+name.encode())
                if "arm-mingw32ce-objdump" in cmd: kw["stdout"].write(b"synthetic disassembly")
            with mock.patch.object(build.sys,"platform","linux"), \
                 mock.patch.object(build.socket,"gethostname",return_value="ant-srv-001"), \
                 mock.patch.object(build.container,"docker",return_value=["docker"]), \
                 mock.patch.object(build.subprocess,"run",side_effect=run), \
                 mock.patch.object(build.native,"check"):
                result=build.build(source,out)
            expected=hashlib.sha256(b"synthetic S2AMLOAD.EXE").hexdigest()
            self.assertEqual(set(result["binaries"]),{"S2AMLOAD.EXE","S2AMCTL.EXE"})
            ctl=next(cmd for cmd in commands if "s2amloadctl.c" in cmd)
            self.assertIn('-DLOAD_EXPECTED_SHA256="'+expected+'"',ctl)
            self.assertIn('-DLOAD_EXPECTED_SIZE=22',ctl)
            self.assertEqual(result["payload_binding"]["sha256"],expected)

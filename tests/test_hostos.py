"""The differences between operating systems (hostos.py), with recorded tool output.

Linux answers come from lsblk, findmnt and udisksctl; here a stand-in plays them, so the tests
run on any system. The disk facts must come out in the shape diskcheck.check reads."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from s2am import container, diskcheck, hostos  # noqa: E402

# lsblk --json --bytes --nodeps -o NAME,PATH,PKNAME,TYPE,FSTYPE,FSVER,SIZE,RM,HOTPLUG,TRAN,RO,PTTYPE,MOUNTPOINT
STICK_PART = {"name": "sdb1", "path": "/dev/sdb1", "pkname": "sdb", "type": "part", "fstype": "vfat",
              "fsver": "FAT32", "size": 31440961536, "rm": True, "hotplug": True, "tran": None, "ro": False,
              "pttype": "dos", "mountpoint": "/media/anna/SYNC"}
STICK_DISK = {"name": "sdb", "path": "/dev/sdb", "pkname": None, "type": "disk", "fstype": None, "fsver": None,
              "size": 31457280000, "rm": True, "hotplug": True, "tran": "usb", "ro": False, "pttype": "dos",
              "mountpoint": None}


class Tools:
    """Plays lsblk, findmnt and udisksctl for one stick; records every command."""

    def __init__(self, part=STICK_PART, disk=STICK_DISK, mounted="/media/anna/SYNC", fail=(), others=(),
                 lsblk_error=None, power_off_error=None, more_mounts=()):
        self.part, self.disk, self.mounted, self.fail = dict(part), dict(disk), mounted, set(fail)
        self.others = [dict(row) for row in others]  # more partitions on the same disk
        self.more_mounts = [dict(row) for row in more_mounts]  # findmnt rows lsblk's one MOUNTPOINT hides
        self.lsblk_error, self.power_off_error = lsblk_error, power_off_error
        self.calls = []

    def __call__(self, command):
        self.calls.append(command)
        tool = command[0] if command[0] != "udisksctl" else f"udisksctl {command[1]}"
        answer = lambda code, out="", err="": subprocess.CompletedProcess(command, code, out, err)  # noqa: E731
        if tool in self.fail:
            return answer(1, "", f"{tool} refused")
        if tool == "findmnt" and "--json" in command:  # every mount on the computer
            mounts = [{"source": "/dev/sda2", "target": "/", "maj:min": "8:2"},
                      {"source": "/dev/sda1", "target": "/boot/efi", "maj:min": "8:1"}]
            if self.mounted:
                mounts.append({"source": "/dev/" + self.part["name"], "target": self.mounted,
                               "maj:min": self.number(self.part)})
            mounts += [{"source": self.path(r), "target": r["mountpoint"], "maj:min": self.number(r)}
                       for r in self.others if r.get("mountpoint") not in (None, "[SWAP]")]
            return answer(0, json.dumps({"filesystems": mounts + self.more_mounts}))
        if tool == "findmnt" and "--mountpoint" in command:
            return answer(0, "/dev/sdb1\n") if command[-1] == self.mounted else answer(1)
        if tool == "findmnt" and "--source" in command:
            return answer(0, (self.mounted or "") + "\n")
        if tool == "lsblk" and self.lsblk_error:
            return answer(1, "", self.lsblk_error)
        if tool == "lsblk" and command[-1] == "FSVER":  # linux_problems asks whether the column exists
            return answer(0, "FAT32\n")
        if tool == "lsblk" and "--list" in command:  # the whole disk and everything on it
            if command[-1] != "/dev/" + self.disk["name"]:
                return answer(32, "", "not a block device")
            rows = [self.disk] + ([self.part] if self.part is not self.disk and self.part["name"] != self.disk["name"]
                                  else []) + self.others
            return answer(0, json.dumps({"blockdevices": [
                {"name": r["name"], "path": self.path(r), "maj:min": self.number(r),
                 "mountpoint": self.mounted if r["name"] == self.part["name"] else r.get("mountpoint")}
                for r in rows]}))
        if tool == "lsblk":
            row = {"/dev/sdb1": self.part, "/dev/sdb": self.disk}.get(command[-1])
            return answer(0, json.dumps({"blockdevices": [row]})) if row else answer(32, "", "not a block device")
        if tool == "udisksctl power-off" and self.power_off_error:
            return answer(1, "", self.power_off_error)
        if tool == "udisksctl unmount":
            self.was, self.mounted = self.mounted, None
            return answer(0)
        if tool == "udisksctl mount":
            self.mounted = getattr(self, "moved_to", None) or self.was
            return answer(0)
        return answer(0)


    @staticmethod
    def path(row):
        return ("/dev/mapper/" if "-" in row["name"] else "/dev/") + row["name"]

    @staticmethod
    def number(row):
        return row.get("maj:min") or "8:%d" % (16 + int("0" + "".join(c for c in row["name"] if c.isdigit())))


def facts(tools, target="/media/anna/SYNC", free=10 ** 9):
    return hostos._linux_info(target, tools, free=lambda path: free, access=lambda path: True, user="anna")


class LinuxDisk(unittest.TestCase):
    def check(self, tools, **kwargs):
        """diskcheck's findings for the played stick, as {first words: level}."""
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(folder))
        info = lambda target: hostos._linux_info(  # noqa: E731
            "/media/anna/SYNC" if target == str(folder) else target, tools, free=lambda path: kwargs.get("free", 10 ** 9),
            access=lambda path: kwargs.get("access", True), user="anna")
        found = diskcheck.check(folder, info)
        return {f.message.split(":")[0]: f.level for f in found}, found

    def test_a_good_stick_passes_every_disk_check(self):
        levels, found = self.check(Tools())
        self.assertEqual({k: v for k, v in levels.items() if v != "ok"}, {})
        for part in ("file system", "size", "external removable disk", "partition scheme", "writable", "free space"):
            self.assertIn(part, levels)
        self.assertFalse(diskcheck.failed(found))

    def test_facts_have_diskutils_shape(self):
        info = facts(Tools())
        self.assertEqual(info["FilesystemName"], "MS-DOS FAT32")
        self.assertEqual((info["TotalSize"], info["ParentWholeDisk"], info["DeviceNode"]), (31440961536, "sdb", "/dev/sdb1"))
        self.assertEqual((info["Internal"], info["Ejectable"], info["BusProtocol"]), (False, True, "USB"))
        self.assertEqual(hostos._linux_info("sdb", Tools())["Content"], hostos.MBR)

    def test_each_wrong_thing_fails_its_own_check(self):
        for name, part, disk, failing in (
                ("exfat", {"fstype": "exfat", "fsver": "1.0"}, {}, "file system"),
                ("fat16", {"fsver": "FAT16"}, {}, "file system"),
                ("too big", {"size": 64 * 1024 ** 3}, {}, "size"),
                ("gpt", {}, {"pttype": "gpt"}, "partition scheme"),
                ("read-only", {"ro": True}, {}, "writable"),
                ("an internal disk", {}, {"rm": False, "hotplug": False, "tran": "sata"}, "external removable disk"),
                ("a hot-pluggable SATA disk", {}, {"rm": False, "hotplug": True, "tran": "sata"}, "external removable disk"),
                ("an NVMe disk in a removable bay", {}, {"rm": True, "hotplug": True, "tran": "nvme"}, "external removable disk"),
                ("a disk on no known bus", {}, {"tran": None}, "external removable disk")):
            with self.subTest(name=name):
                levels, found = self.check(Tools({**STICK_PART, **part}, {**STICK_DISK, **disk}))
                self.assertEqual(levels[failing], "fail")
                self.assertTrue(diskcheck.failed(found))

    def test_a_usb_disk_that_carries_the_running_system_is_never_a_stick(self):
        for name, others in (("swap", [{"name": "sdb2", "mountpoint": "[SWAP]"}]),
                             ("root", [{"name": "sdb2", "mountpoint": "/"}]),
                             ("boot", [{"name": "sdb2", "mountpoint": "/boot/efi"}]),
                             ("root on LVM", [{"name": "sdb2"}, {"name": "vg-root", "mountpoint": "/"}]),
                             ("home", [{"name": "sdb2", "mountpoint": "/home"}])):
            with self.subTest(name=name):
                levels, found = self.check(Tools(others=others))
                self.assertEqual(levels["external removable disk"], "fail")
                self.assertEqual(levels["in use by this computer"], "fail")
                self.assertTrue(diskcheck.failed(found))
        info = facts(Tools(others=[{"name": "sdb2", "mountpoint": "[SWAP]"}]))
        self.assertEqual((info["Internal"], info["Ejectable"], info["SystemMounts"]), (True, False, ["[SWAP]"]))

    def test_a_partition_mounted_twice_is_judged_by_every_mount_not_the_one_lsblk_shows(self):
        for name, mount in (("the stick itself also at /boot/efi",
                             {"source": "/dev/sdb1", "target": "/boot/efi", "maj:min": "8:17"}),
                            ("a folder of it bound into /srv",
                             {"source": "/dev/sdb1[/data]", "target": "/srv/data", "maj:min": "8:17"}),
                            ("root on LVM, named differently by findmnt",
                             {"source": "/dev/dm-0", "target": "/", "maj:min": "253:0"})):
            with self.subTest(name=name):
                tools = Tools(others=[{"name": "vg-root", "maj:min": "253:0"}], more_mounts=[mount])
                levels, found = self.check(tools)
                self.assertEqual(levels["external removable disk"], "fail")
                self.assertIn(mount["target"], " ".join(f.message for f in found))

    def test_mounts_of_other_disks_do_not_count(self):
        tools = Tools(more_mounts=[{"source": "/dev/sdc1", "target": "/mnt/backup", "maj:min": "8:33"}])
        self.assertEqual(facts(tools)["SystemMounts"], [])

    def test_a_findmnt_that_cannot_list_the_mounts_is_an_unreadable_disk(self):
        class NoList(Tools):
            def __call__(self, command):
                if command[0] == "findmnt" and "--json" in command:
                    return subprocess.CompletedProcess(command, 1, "", "findmnt: failed")
                return super().__call__(command)
        levels, found = self.check(NoList())
        self.assertIn("could not be read", found[0].message)

    def test_a_second_stick_volume_on_the_same_disk_is_not_system_use(self):
        levels, found = self.check(Tools(others=[{"name": "sdb2", "mountpoint": "/run/media/anna/DATA"},
                                                 {"name": "sdb3"}]))
        self.assertEqual({k: v for k, v in levels.items() if v != "ok"}, {})

    def test_a_stick_mounted_by_hand_somewhere_else_is_not_taken(self):
        self.assertEqual(self.check(Tools(others=[{"name": "sdb2", "mountpoint": "/mnt/usb"}]))[0][
            "external removable disk"], "fail")

    def test_an_lsblk_without_fsver_says_it_is_too_old_and_not_that_the_stick_is_bad(self):
        tools = Tools(lsblk_error="lsblk: unknown column: FSVER")
        levels, found = self.check(tools)
        self.assertIn("util-linux 2.35", found[0].message)
        self.assertIn("could not be read", found[0].message)

    def test_older_lsblk_prints_flags_as_text(self):
        tools = Tools({**STICK_PART, "rm": "1", "hotplug": "1", "ro": "0"}, {**STICK_DISK, "rm": "1", "hotplug": "1", "ro": "0"})
        self.assertEqual(self.check(tools)[0]["external removable disk"], "ok")
        self.assertEqual(self.check(Tools({**STICK_PART, "ro": "1"}))[0]["writable"], "fail")

    def test_a_stick_without_a_partition_table_fails(self):
        whole = {**STICK_DISK, "fstype": "vfat", "fsver": "FAT32", "pttype": None}
        tools = Tools(part=whole, disk=whole)
        tools.part["pkname"] = None
        self.assertEqual(self.check(tools)[0]["partition scheme"], "fail")

    def test_a_stick_this_user_cannot_write_to_fails(self):
        self.assertEqual(self.check(Tools(), access=False)[0]["writable"], "fail")

    def test_little_free_space_is_a_warning(self):
        self.assertEqual(self.check(Tools(), free=10 ** 6)[0]["free space"], "warn")

    def test_a_folder_that_is_not_a_mount_or_a_tool_that_fails_is_a_failed_check_not_a_crash(self):
        for tools in (Tools(mounted="/media/anna/OTHER"), Tools(fail={"lsblk"}), Tools(fail={"findmnt"})):
            levels, found = self.check(tools)
            self.assertTrue(diskcheck.failed(found))
            self.assertIn("could not be read", found[0].message)

    def test_unusable_lsblk_output_is_an_error(self):
        def broken(command):
            return subprocess.CompletedProcess(command, 0, "/dev/sdb1\n" if command[0] == "findmnt" else "{}", "")
        with self.assertRaises(hostos.HostError):
            hostos._linux_info("/media/anna/SYNC", broken, free=lambda path: 0, access=lambda path: True)


class LinuxEject(unittest.TestCase):
    def setUp(self):  # sticks show up under /media/anna
        patcher = mock.patch.object(hostos.getpass, "getuser", return_value="anna")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_disk_the_computer_uses_is_never_unmounted_or_powered_off(self):
        tools = Tools(others=[{"name": "sdb2", "mountpoint": "[SWAP]"}])
        worked, advice = hostos.eject(Path("/media/anna/SYNC"), "Linux", tools)
        self.assertFalse(worked)
        self.assertIn("[SWAP]", advice)
        self.assertFalse(any(c[0] == "udisksctl" for c in tools.calls))
        self.assertFalse(hostos.remount(Path("/media/anna/SYNC"), "Linux", tools, wait=lambda s: None))
        self.assertFalse(any(c[0] == "udisksctl" for c in tools.calls))

    def test_eject_unmounts_then_powers_off(self):
        tools = Tools()
        self.assertEqual(hostos.eject(Path("/media/anna/SYNC"), "Linux", tools), (True, ""))
        done = [c[:2] + c[-1:] for c in tools.calls if c[0] == "udisksctl"]
        self.assertEqual(done, [["udisksctl", "unmount", "/dev/sdb1"], ["udisksctl", "power-off", "/dev/sdb"]])

    def test_a_failed_unmount_says_so_and_does_not_power_off(self):
        tools = Tools(fail={"udisksctl unmount"})
        worked, advice = hostos.eject(Path("/media/anna/SYNC"), "Linux", tools)
        self.assertFalse(worked)
        self.assertIn("unmount it in your file manager", advice)
        self.assertFalse(any(c[:2] == ["udisksctl", "power-off"] for c in tools.calls))

    def test_a_refused_power_off_is_not_called_ejected(self):
        tools = Tools(power_off_error="Error powering off drive: The drive in use: Device /dev/sdb2 is mounted")
        worked, advice = hostos.eject(Path("/media/anna/SYNC"), "Linux", tools)
        self.assertFalse(worked)
        self.assertIn("could not be switched off", advice)
        self.assertIn("/dev/sdb2 is mounted", advice)
        # only the stick's own volume was unmounted, nothing else on the disk
        unmounted = [c[-1] for c in tools.calls if c[:2] == ["udisksctl", "unmount"]]
        self.assertEqual(unmounted, ["/dev/sdb1"])

    def test_a_stick_without_a_partition_table_is_powered_off_by_its_own_device(self):
        whole = {**STICK_DISK, "name": "sdb1", "fstype": "vfat", "fsver": "FAT32", "pttype": None}
        tools = Tools(part=whole, disk=whole)
        self.assertEqual(hostos.eject(Path("/media/anna/SYNC"), "Linux", tools), (True, ""))
        self.assertIn(["udisksctl", "power-off", "--block-device", "/dev/sdb1"], tools.calls)

    def test_eject_of_something_that_is_not_mounted_fails_cleanly(self):
        self.assertFalse(hostos.eject(Path("/media/anna/GONE"), "Linux", Tools())[0])


class LinuxRemount(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.folder))
        # the stick is a real folder here, so the folder it sits in plays /media/<you>
        patcher = mock.patch.object(hostos, "volume_roots", lambda system="Linux", user=None: [self.folder.parent])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_remount_comes_back_at_the_same_place(self):
        tools = Tools(mounted=str(self.folder))
        self.assertTrue(hostos.remount(self.folder, "Linux", tools, wait=lambda s: None))
        self.assertEqual([c[1] for c in tools.calls if c[0] == "udisksctl"], ["unmount", "mount"])

    def test_remount_at_another_place_is_not_accepted(self):
        tools = Tools(mounted=str(self.folder))
        tools.moved_to = str(self.folder) + "1"  # the system picked a new name
        self.assertFalse(hostos.remount(self.folder, "Linux", tools, wait=lambda s: None))

    def test_a_busy_stick_is_tried_five_times_then_given_up(self):
        tools = Tools(mounted=str(self.folder), fail={"udisksctl unmount"})
        waits = []
        self.assertFalse(hostos.remount(self.folder, "Linux", tools, wait=waits.append))
        self.assertEqual(len(waits), 5)
        self.assertFalse(any(c[:2] == ["udisksctl", "mount"] for c in tools.calls))

    def test_a_failed_mount_is_a_failure(self):
        self.assertFalse(hostos.remount(self.folder, "Linux", Tools(mounted=str(self.folder), fail={"udisksctl mount"}),
                                        wait=lambda s: None))


@unittest.skipUnless(sys.platform.startswith("linux"), "needs a real Linux system")
class RealLinux(unittest.TestCase):
    """The real lsblk and findmnt of the machine the tests run on, asked about its own root disk:
    whatever that disk is, the answer must be the facts in diskutil's shape or a HostError."""

    def test_the_root_disk_is_described_or_refused_cleanly(self):
        try:
            info = hostos._linux_info("/")
        except hostos.HostError:
            return  # for example an overlay root in a container: not a disk, said so
        for key in ("FilesystemName", "TotalSize", "Internal", "Ejectable", "BusProtocol", "WritableVolume", "FreeSpace"):
            self.assertIn(key, info)
        self.assertGreater(info["TotalSize"], 0)
        self.assertNotEqual(info["FilesystemName"], "MS-DOS FAT32")
        levels = {f.message.split(":")[0]: f.level for f in diskcheck.check(Path("/"), hostos._linux_info)}
        self.assertEqual(levels["file system"], "fail")  # a system disk is never taken for a stick

    def test_a_folder_that_is_not_a_mount_point_is_refused(self):
        with self.assertRaises(hostos.HostError):
            hostos._linux_info(tempfile.gettempdir() + "/no-such-mount-point")


class LinuxReady(unittest.TestCase):
    def test_missing_tools_are_named(self):
        problems = hostos.linux_problems(Tools(), which=lambda tool: None if tool == "udisksctl" else "/usr/bin/" + tool)
        self.assertEqual(len(problems), 1)
        self.assertIn("udisksctl", problems[0])
        self.assertIn("udisks2", problems[0])

    def test_an_lsblk_without_fsver_is_too_old(self):
        problems = hostos.linux_problems(Tools(lsblk_error="lsblk: unknown column: FSVER"), which=lambda t: "/usr/bin/" + t)
        self.assertEqual(problems, [hostos.TOO_OLD])

    def test_a_ready_computer_has_no_problems(self):
        self.assertEqual(hostos.linux_problems(Tools(), which=lambda t: "/usr/bin/" + t), [])


class DockerOnEachSystem(unittest.TestCase):
    @unittest.skipUnless(hasattr(__import__("os"), "getuid"), "no uid on this system")
    def test_files_from_the_container_belong_to_the_user(self):
        import os
        mine = ["-u", f"{os.getuid()}:{os.getgid()}"]
        self.assertEqual(container.user_args("Darwin", security=lambda: '["name=rootless"]'), mine)
        self.assertEqual(container.user_args("Linux", security=lambda: '["name=seccomp,profile=builtin"]'), mine)
        self.assertEqual(container.user_args("Linux", security=lambda: ""), mine)  # docker info failed

    def test_rootless_docker_runs_the_tools_as_the_containers_root_which_is_the_user(self):
        security = '["name=seccomp,profile=builtin","name=rootless","name=cgroupns"]'
        if hasattr(__import__("os"), "getuid"):
            self.assertEqual(container.user_args("Linux", security=lambda: security), ["-u", "0:0"])

    def test_an_x86_computer_or_a_mac_needs_no_emulation(self):
        for system, machine in (("Linux", "x86_64"), ("Linux", "AMD64"), ("Darwin", "arm64")):
            with self.subTest(machine=machine):
                self.assertIsNone(container.emulation_problem(system, machine, Path("/no/such/binfmt")))

    def test_an_arm_linux_computer_needs_x86_emulation(self):
        binfmt = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(binfmt))
        (binfmt / "status").write_text("enabled")
        problem = container.emulation_problem("Linux", "aarch64", binfmt)
        self.assertIn("aarch64", problem)
        self.assertIn("qemu-user-static", problem)
        self.assertIn("qemu-user-static", container.emulation_problem("Linux", "aarch64", Path("/no/such/binfmt")))
        (binfmt / "qemu-x86_64").write_text("disabled\ninterpreter /usr/libexec/qemu-binfmt/x86_64-binfmt-P\n")
        self.assertIsNotNone(container.emulation_problem("Linux", "aarch64", binfmt))  # registered, switched off
        (binfmt / "qemu-x86_64").write_text("enabled\ninterpreter /usr/libexec/qemu-binfmt/x86_64-binfmt-P\n")
        self.assertIsNone(container.emulation_problem("Linux", "aarch64", binfmt))
        (binfmt / "status").write_text("disabled\n")  # binfmt_misc itself switched off
        self.assertIsNotNone(container.emulation_problem("Linux", "aarch64", binfmt))


class Places(unittest.TestCase):
    def test_where_sticks_are(self):
        self.assertEqual(hostos.volume_roots("Darwin"), [Path("/Volumes")])
        self.assertEqual(hostos.volume_roots("Linux", "anna"), [Path("/media/anna"), Path("/run/media/anna")])

    def test_a_volume_is_the_top_folder_only(self):
        for path, system, good in (("/Volumes/SYNC", "Darwin", True), ("/Volumes/SYNC/s2am", "Darwin", False),
                                   ("/media/anna/SYNC", "Linux", True), ("/run/media/anna/SYNC", "Linux", True),
                                   ("/media/berit/SYNC", "Linux", False), ("/home/anna/SYNC", "Linux", False),
                                   ("/media/anna", "Linux", False)):
            with self.subTest(path=path):
                self.assertEqual(hostos.is_volume(Path(path), system, "anna"), good)

    def test_windows_is_refused_with_the_issue(self):
        for call in (lambda: hostos.volume_roots("Windows"), lambda: hostos.eject(Path("E:/"), "Windows"),
                     lambda: hostos.remount(Path("E:/"), "Windows")):
            with self.assertRaises(hostos.HostError) as caught:
                call()
            self.assertIn("issues/6", str(caught.exception))

    def test_formatting_advice_names_the_systems_own_tool(self):
        self.assertIn("Disk Utility", " ".join(hostos.format_steps("Darwin")))
        linux = " ".join(hostos.format_steps("Linux"))
        self.assertIn("Disks", linux)
        self.assertIn("MBR", linux)
        self.assertIn("FAT", linux)


if __name__ == "__main__":
    unittest.main()

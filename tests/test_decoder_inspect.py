"""Independent decoder evidence must never turn a missing report into installation success."""
import hashlib
import json
import tempfile
import unittest
import zlib
from pathlib import Path

from s2am import decoder_inspect as inspect, stick
from s2am.job import Job, meta, stage
from s2am.state import Store

SERIAL = "XV31M13H"
TARGET = "20261115-205200-dec-abcd"
OWN = "20261116-190000-decdiag-abcd"
NAMES = ("avcodec-56.dll", "avutil-54.dll", "avformat-56.dll")


class Evidence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.expected = {n: {"old_sha256": hashlib.sha256(("old"+n).encode()).hexdigest(),
                             "new_sha256": hashlib.sha256(("new"+n).encode()).hexdigest()}
                         for n in NAMES}
        self.job = Job(SERIAL, "decdiag", id=OWN,
                       params={"target": TARGET, "expected": self.expected})

    def report(self, states=("new", "new", "new")):
        (self.root / "files").mkdir(exist_ok=True)
        lines = [f"S|s2am-decdiag-v1|{OWN}|{TARGET}"]
        for label in inspect.LABELS:
            if label.startswith("active-"):
                name = label[len("active-"):]
                data = (states[NAMES.index(name)] + name).encode()
            else:
                data = label.encode()
            (self.root / "files" / label).write_bytes(data)
            lines.append(f"F|{label}|128|0|{len(data)}|1|2|copied|0|{len(data)}|{zlib.crc32(data)}")
        lines.extend(f"D|{name}|16|0|1|0|0|100|0|200" for name in inspect.DIRECTORIES)
        lines.extend(["P|exited|0|0|1|0|1", "C|unavailable|2|0|0|0|0", "T|complete"])
        (self.root / "decdiag.txt").write_text("\n".join(lines)+"\n")
        (self.root / "done.txt").write_text(OWN)

    def test_candidate_stock_and_mixed_on_disk(self):
        for states, expected in ((("new",)*3, "candidate"), (("old",)*3, "stock"),
                                 (("new", "old", "new"), "mixed"),
                                 (("other",)*3, "unknown")):
            self.report(states)
            self.assertEqual(inspect.analyze(self.root, self.job)["decoder"], expected)

    def test_missing_marker_or_wrong_identity_is_not_complete(self):
        self.report()
        (self.root / "done.txt").unlink()
        self.assertFalse(inspect.analyze(self.root, self.job)["complete"])
        (self.root / "done.txt").write_text(TARGET)
        self.assertFalse(inspect.analyze(self.root, self.job)["complete"])

    def test_same_size_corruption_rejected(self):
        self.report()
        file = self.root / "files" / inspect.LABELS[0]
        file.write_bytes(b"x"*file.stat().st_size)
        self.assertFalse(inspect.analyze(self.root, self.job)["complete"])

    def test_symlink_and_duplicate_record_rejected(self):
        self.report()
        file = self.root / "files" / inspect.LABELS[0]
        data = file.read_bytes()
        file.unlink()
        (self.root / "outside").write_bytes(data)
        file.symlink_to(self.root / "outside")
        self.assertFalse(inspect.analyze(self.root, self.job)["complete"])
        file.unlink()
        file.write_bytes(data)
        path = self.root / "decdiag.txt"
        lines = path.read_text().splitlines()
        path.write_text("\n".join(lines[:-1]+[lines[1], lines[-1]]))
        self.assertFalse(inspect.analyze(self.root, self.job)["complete"])

    def test_missing_active_file_gives_complete_inspection_unknown_decoder(self):
        self.report()
        path = self.root / "decdiag.txt"
        lines = path.read_text().splitlines()
        lines[1] = f"F|{inspect.LABELS[0]}|0|0|0|0|0|attrs-error|2|0|0"
        path.write_text("\n".join(lines))
        result = inspect.analyze(self.root, self.job)
        self.assertTrue(result["complete"])
        self.assertEqual(result["decoder"], "unknown")

    def test_unchanged_common_file_is_not_a_mixed_set(self):
        self.expected[NAMES[0]]["old_sha256"] = self.expected[NAMES[0]]["new_sha256"]
        self.report()
        self.assertEqual(inspect.analyze(self.root, self.job)["decoder"], "candidate")

    def test_stage_uses_direct_native_launcher_without_active_payload(self):
        upstream = self.root / "upstream/FullPack/RemoveExtPack"
        upstream.mkdir(parents=True)
        (upstream / "MortScript.exe").write_bytes(b"interpreter")
        (upstream / "RemoveExtPack.exe").write_bytes(b"runner")
        work = self.root / "job"
        stage(self.job, self.root / "upstream", work, {"s2amdiag.exe": b"native"})
        metadata = meta(self.job).decode("utf-16le")
        self.assertIn("/s2amdiag.exe", metadata)
        self.assertNotIn("NEED_REBOOT", metadata)
        target = work / "payload" / self.job.job_dir.lstrip("/")
        self.assertEqual((target / "target.txt").read_text().strip(), TARGET)
        script = (target / "probe.mscr").read_text()
        self.assertIn("probe-done.txt", script)
        self.assertNotIn(TARGET, script)
        self.assertNotIn("AutoKit", script)
        self.assertFalse((work / "payload/SyncExtendedPack/Apps").exists())

    def test_invalid_target_refused_before_staging(self):
        self.job.params["target"] = "../escape"
        with self.assertRaises(ValueError):
            stage(self.job, self.root, self.root / "absent", {"s2amdiag.exe": b"native"})
        self.assertFalse((self.root / "absent").exists())

    def test_import_rejects_usb_changed_expected_hashes_and_keeps_local_identity(self):
        store = Store(self.root / "store")
        trusted = json.loads(self.job.to_json())
        store.save_job(SERIAL, OWN, trusted)
        usb = self.root / "usb"
        pending = usb / "s2am/pending"
        pending.mkdir(parents=True)
        for change in ("hash", "kind"):
            changed = json.loads(self.job.to_json())
            if change == "hash":
                changed["params"]["expected"][NAMES[0]]["new_sha256"] = "0"*64
            else:
                changed["kind"] = "inv"
            (pending / f"{OWN}.json").write_text(json.dumps(changed))
            result = stick.import_reports(usb, store, require_volume=False)
            self.assertEqual(result[0]["status"], "rejected")
            self.assertEqual(store.job(SERIAL, OWN), trusted)

    def test_contradictory_probe_outcome_is_rejected(self):
        self.report()
        path = self.root / "decdiag.txt"
        path.write_text(path.read_text().replace("P|exited|0|0|1|0|1", "P|exited|5|258|1|0|1"))
        self.assertFalse(inspect.analyze(self.root, self.job)["complete"])

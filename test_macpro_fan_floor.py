#!/usr/bin/python3 -I
"""Tests for macpro-fan-floor against a fake sysfs tree. Standard library only."""
import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_loader = importlib.machinery.SourceFileLoader("mff", os.path.join(HERE, "macpro-fan-floor"))
_spec = importlib.util.spec_from_loader("mff", _loader)
mff = importlib.util.module_from_spec(_spec)
_loader.exec_module(mff)


class FakeSys:
    def __init__(self, cpu=50.0, gpus=(50.0, 50.0), fmax=1950, fmin=790):
        self.tmp = tempfile.TemporaryDirectory()
        r = self.root = self.tmp.name
        self.smc = os.path.join(r, mff.SMC_REL)
        os.makedirs(self.smc)
        ct = os.path.join(r, "sys/devices/platform/coretemp.0/hwmon/hwmon4")
        os.makedirs(ct)
        self.w(os.path.join(ct, "temp1_label"), "Package id 0")
        self.w(os.path.join(ct, "temp2_label"), "Core 0")
        self.w(os.path.join(ct, "temp2_input"), "99000")
        self.cpu_file = os.path.join(ct, "temp1_input")
        self.gpu_files = []
        for i, n in enumerate(["nvme", "amdgpu", "amdgpu"]):
            d = os.path.join(r, f"sys/class/hwmon/hwmon{i}")
            os.makedirs(d)
            self.w(os.path.join(d, "name"), n)
            if n == "amdgpu":
                self.gpu_files.append(os.path.join(d, "temp1_input"))
            else:
                self.w(os.path.join(d, "temp1_input"), "105000")
        self.set(cpu, gpus)
        for k, v in {"fan1_max": fmax, "fan1_min": fmin, "fan1_manual": 0, "fan1_input": 790}.items():
            self.w(os.path.join(self.smc, k), str(v))

    @staticmethod
    def w(path, val):
        with open(path, "w") as f:
            f.write(val + "\n")

    def set(self, cpu=None, gpus=None):
        if cpu is not None:
            self.w(self.cpu_file, cpu if isinstance(cpu, str) else str(int(cpu * 1000)))
        if gpus is not None:
            for f, g in zip(self.gpu_files, gpus):
                self.w(f, g if isinstance(g, str) else str(int(g * 1000)))

    def fan_min(self):
        with open(os.path.join(self.smc, "fan1_min")) as f:
            return int(f.read())

    def close(self):
        self.tmp.cleanup()


class Base(unittest.TestCase):
    def setUp(self):
        self.fs = FakeSys()
        self.ctl = mff.Controller(root=self.fs.root, base=950)
        self._stdout = sys.stdout
        sys.stdout = open(os.devnull, "w")

    def tearDown(self):
        sys.stdout.close()
        sys.stdout = self._stdout
        self.fs.close()

    def settle(self, n=60):
        for _ in range(n):
            rpm, info, _ = self.ctl.step()
        return rpm, info


class CurveTests(Base):
    def test_interp_points(self):
        pts = mff.cpu_curve(950, 1950)
        self.assertEqual(mff.interp(40, pts), 950)
        self.assertEqual(mff.interp(60, pts), 950)
        self.assertAlmostEqual(mff.interp(70, pts), 1225)
        self.assertEqual(mff.interp(80, pts), 1500)
        self.assertEqual(mff.interp(90, pts), 1800)
        self.assertEqual(mff.interp(100, pts), 1950)

    def test_idle_is_base_and_written(self):
        rpm, _, _ = self.ctl.step()
        self.assertEqual(rpm, 950)
        self.assertEqual(self.fs.fan_min(), 950)

    def test_cpu_hot_ramps_immediately(self):
        self.ctl.step()
        self.fs.set(cpu=80)
        rpm, _, _ = self.ctl.step()
        self.assertEqual(rpm, 1500)
        self.assertEqual(self.fs.fan_min(), 1500)

    def test_gpu_hot_wins(self):
        self.fs.set(cpu=50, gpus=(50, 85))
        rpm, _, _ = self.ctl.step()
        self.assertEqual(rpm, 1500)

    def test_uses_package_sensor_not_hot_core_or_other_hwmon(self):
        # Core 0 at 99C and nvme at 105C must be ignored.
        rpm, info, _ = self.ctl.step()
        self.assertEqual(info["cpu"], 50.0)
        self.assertEqual(rpm, 950)


class SafetyTests(Base):
    def test_clamped_to_fan_max(self):
        self.fs.set(cpu=105)
        rpm, _, _ = self.ctl.step()
        self.assertEqual(rpm, 1950)

    def test_never_below_stock(self):
        ctl = mff.Controller(root=self.fs.root, base=790)
        rpm, _, _ = ctl.step()
        self.assertGreaterEqual(rpm, mff.STOCK_MIN)

    def test_base_out_of_range_rejected(self):
        with self.assertRaises(ValueError):
            mff.Controller(root=self.fs.root, base=500)
        with self.assertRaises(ValueError):
            mff.Controller(root=self.fs.root, base=1600)

    def test_invalid_cpu_reading_gives_safe_floor(self):
        for bad in ("garbage", "-53000", "0", "150000"):
            ctl = mff.Controller(root=self.fs.root, base=950)
            self.fs.set(cpu=bad)
            rpm, info, _ = ctl.step()
            self.assertEqual(rpm, mff.SAFE_FLOOR, bad)
            self.assertIn("cpu-invalid", info["reasons"])

    def test_missing_cpu_sensor_gives_safe_floor(self):
        os.remove(self.fs.cpu_file)
        rpm, _, _ = self.ctl.step()
        self.assertEqual(rpm, mff.SAFE_FLOOR)

    def test_missing_gpu_gives_safe_floor(self):
        os.remove(self.fs.gpu_files[1])
        rpm, info, _ = self.ctl.step()
        self.assertEqual(rpm, mff.SAFE_FLOOR)
        self.assertTrue(any(r.startswith("gpu-invalid") for r in info["reasons"]))

    def test_safe_floor_does_not_mask_hotter_demand(self):
        os.remove(self.fs.gpu_files[1])
        self.fs.set(cpu=90)
        rpm, _, _ = self.ctl.step()
        self.assertEqual(rpm, 1800)

    def test_implausible_fan_max_uses_default(self):
        FakeSys.w(os.path.join(self.fs.smc, "fan1_max"), "0")
        self.fs.set(cpu=105)
        rpm, info, _ = self.ctl.step()
        self.assertEqual(info["fmax"], mff.DEFAULT_MAX)
        self.assertEqual(rpm, mff.DEFAULT_MAX)

    def test_restore_writes_stock(self):
        self.fs.set(cpu=85)
        self.ctl.step()
        self.ctl.restore()
        self.assertEqual(self.fs.fan_min(), mff.STOCK_MIN)

    def test_main_restores_on_exit(self):
        self.fs.set(cpu=85)
        mff.main(["--root", self.fs.root, "--once"])
        self.assertEqual(self.fs.fan_min(), mff.STOCK_MIN)

    def test_dry_run_never_writes(self):
        ctl = mff.Controller(root=self.fs.root, base=950, dry_run=True)
        self.fs.set(cpu=85)
        ctl.step()
        ctl.restore()
        self.assertEqual(self.fs.fan_min(), 790)


class SmoothingTests(Base):
    def test_slow_decay_then_reaches_base_exactly(self):
        self.fs.set(cpu=90)
        self.ctl.step()
        self.fs.set(cpu=40)
        rpm, _, _ = self.ctl.step()
        self.assertEqual(rpm, 1750)
        rpm, _ = self.settle()
        self.assertEqual(rpm, 950)
        self.assertEqual(self.fs.fan_min(), 950)

    def test_small_changes_not_written(self):
        self.ctl.step()  # 950 written
        self.fs.set(cpu=60.5)  # ~964 rpm, delta < 25
        self.ctl.step()
        self.assertEqual(self.fs.fan_min(), 950)
        self.fs.set(cpu=62)  # ~1005, delta >= 25
        self.ctl.step()
        self.assertEqual(self.fs.fan_min(), 1005)


class ReviewRegressionTests(Base):
    def test_hot_valid_gpu_not_masked_by_missing_gpu(self):  # S1
        os.remove(self.fs.gpu_files[1])
        self.fs.set(cpu=50, gpus=(97,))
        rpm, info, _ = self.ctl.step()
        self.assertEqual(rpm, 1950)

    def test_smoothed_value_clamped_when_fan_max_drops(self):  # S2
        FakeSys.w(os.path.join(self.fs.smc, "fan1_max"), "2062")
        self.fs.set(cpu=105)
        self.assertEqual(self.ctl.step()[0], 2062)
        FakeSys.w(os.path.join(self.fs.smc, "fan1_max"), "1950")
        self.fs.set(cpu=40)
        rpm, _, _ = self.ctl.step()
        self.assertLessEqual(rpm, 1950)
        self.assertLessEqual(self.fs.fan_min(), 1950)

    def test_failed_write_not_recorded_and_main_exits_nonzero(self):  # S4
        path = os.path.join(self.fs.smc, "fan1_min")
        os.remove(path)
        os.mkdir(path)  # writes now fail
        rpm, _, ok = self.ctl.step()
        self.assertFalse(ok)
        self.assertIsNone(self.ctl.last_written)
        self.assertEqual(mff.main(["--root", self.fs.root, "--interval", "0"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=1)

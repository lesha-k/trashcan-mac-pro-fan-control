# trashcan-mac-pro-fan-control

Fan control for the late-2013 Mac Pro (MacPro6,1, the "trashcan") on Linux. It
raises the SMC fan floor from CPU and GPU temperatures, while the SMC itself
stays in automatic mode.

One small Python script (standard library only), a hardened systemd unit, an
installer with a one-command rollback, and tests that run against a fake sysfs
tree.

## The problem

On Linux, the MacPro6,1 is left with the SMC's built-in fan curve, and that
curve is very conservative. Under sustained full CPU load on the unit this was
written on, the fan target stayed at the 790 rpm minimum until the CPU cores
reached about 80 °C.

The behaviour is not specific to Linux. [Crystalidea measured a stock 2013 Mac
Pro under Windows](https://crystalidea.com/blog/optimizing-thermals-in-mac-pro-2013):
the fan ramped only at about 80 °C, and a fixed 1500 rpm fan lowered both CPU
and GPU temperatures by about 9 °C.

The CPU and both GPUs share one heatsink and one fan. A controller that reads
only CPU temperatures, as [mbpfan](https://github.com/linux-on-mac/mbpfan)
does, cannot see half of the heat.

## How it works

Every 2 seconds the controller reads two kinds of temperature:

- the CPU package (`coretemp`, `Package id 0`)
- both `amdgpu` hwmon edge temperatures

It maps each through a curve and writes the highest result to `fan1_min`:

| Sensor | Temperature → floor (rpm) |
|---|---|
| CPU package | ≤60 °C → base, 80 → 1500, 90 → 1800, ≥92 → `fan1_max` |
| Each GPU | ≤65 °C → base, 85 → 1500, 95 → 1800, ≥97 → `fan1_max` |

The default base is 950 rpm (`--base`, allowed range 790–1500). Between curve
points the floor is linear.

It only ever writes `fan1_min`. It never sets `fan1_manual`, so the SMC keeps
control and can always spin the fan faster than the floor.

Safety behaviour:

- **Range:** writes are clamped to 790 (stock) … the current `fan1_max`, which
  the SMC reports and which varies.
- **Bad sensors:** a missing sensor, a reading outside 10–110 °C, or fewer than
  two GPUs found sets a floor of at least 1200 rpm. A hotter valid sensor still
  wins.
- **Ramping:** up is immediate; down is at most 50 rpm per step. Changes under
  25 rpm are not written.
- **Write checks:** every write is read back. After 5 consecutive failed writes
  the process exits non-zero instead of reporting healthy.
- **Stopping:** stopping, a crash or a watchdog kill restores 790 rpm, which is
  stock behaviour. The script handles this itself, and `ExecStopPost` in the
  unit covers it too.
- **Watchdog:** systemd `Type=notify` with `WatchdogSec=30`. Readiness and
  watchdog pings are sent only after a successful step.
- **Sandbox:** no capabilities, no network, read-only filesystem except `/sys`.
  `systemd-analyze security` reports an exposure of 1.1.

Logs contain only floor changes, plus a heartbeat every 10 minutes:

```
fan1_min 950 -> 1225 (cpu 70C, gpu 52/49C, fan 958)
```

## Measured effect

One unit only: Xeon E5-1680 v2 (8 cores), FirePro D300, Fedora 44, kernel
7.1. The same guarded CPU ramp was run twice on the same day: `stress-ng
--cpu-method matrixprod`, 4, 8 and then 16 workers, stopped automatically at
80 °C or on any throttling.

| | Stock SMC curve | With this controller |
|---|---|---|
| 16-thread stage | stopped by the 80 °C guard after 255 s | ran the full 300 s |
| CPU cores | 80 °C and still rising (~2 °C/min) | levelled off at ~74 °C |
| Fan target under load | 790 rpm | 1225–1335 rpm |
| SMC `TC0P` (CPU proximity) peak | 61.75 °C | 55.5 °C |
| SMC `TM1a` peak | 77.5 °C | 72.5 °C |
| After load | rose to 877 rpm only during cooldown | back to 950 rpm within ~20 s |

Background load differed slightly between the runs, and room temperature was
not measured. Thermal throttle counters stayed at 0 in both runs.

## Requirements

- A MacPro6,1. The installer refuses to run on anything else.
- Linux with the `applesmc`, `coretemp` and `amdgpu` drivers loaded.
  `/sys/devices/platform/applesmc.768/fan1_min` must exist.
- systemd and Python 3 (standard library only).

## Install

```sh
git clone https://github.com/lesha-k/trashcan-mac-pro-fan-control.git
cd trashcan-mac-pro-fan-control

python3 -I test_macpro_fan_floor.py   # optional; the installer runs the tests too
./macpro-fan-floor --dry-run --once   # print one decision without writing anything
sudo ./install.sh probe               # check the SMC accepts fan1_min, then restore it
sudo ./install.sh install
```

The steps of `install` are:

1. Stop any existing instance.
2. Run the probe: write 1000 rpm, read it back, wait for the fan to follow, then
   restore the original value.
3. Run the tests.
4. Copy root-owned files to `/usr/local/sbin/macpro-fan-floor` and
   `/etc/systemd/system/macpro-fan-floor.service`.
5. Enable and start the service.

The probe restores the original value even if it fails.

## Operate

```sh
./install.sh status                 # unit state plus fan1_min, fan1_input and fan1_manual
journalctl -u macpro-fan-floor -f
sudo ./install.sh rollback          # disable, remove both files, write 790
```

To change the idle floor, edit `--base` in `macpro-fan-floor.service` and run
`sudo ./install.sh install` again. The curves are near the top of the script.

## Caveats

- **Limited testing:** tested on one machine with D300 GPUs. D500 and D700
  cards and the 12-core CPU run hotter, and the curves are not tuned for them.
  Watch the logs before trusting it.
- **Not yet tested:** a reboot with the service enabled, and heavy combined
  CPU and GPU load.
- **Missing sensors:** no usable Linux sensor exists for the PSU or VRMs, so the
  controller cannot react to them.
- **SMC writes:** this writes to the SMC, and the software comes with no
  warranty; see [LICENSE](LICENSE). To get stock behaviour back, run
  `rollback`, or stop the service.

## License

MIT

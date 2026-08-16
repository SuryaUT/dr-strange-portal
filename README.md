# Dr. Strange Sling Ring

A wearable sling ring that opens a portal when you draw a circle in the air, and
closes it when you draw one the other way. No buttons, no phone, no cameras
watching your hand. Just a motion sensor on your finger and a bit of signal
processing.

Circle clockwise and the portal opens. Circle counter clockwise and it closes.
It takes about one and a half turns, roughly 1.2 seconds, and it stays open
after you drop your hand.

Everything here is open source. The electronics are three parts, the case prints
in one go on any hobby printer, and the whole thing runs on a battery the size of
a postage stamp.

## How it works

When you swing your hand in a circle, your arm is doing something very specific:
it is pulling the ring toward the center of that circle the whole time. That pull
is centripetal acceleration, and the accelerometer feels it as a vector that
sweeps a full 360 degrees over one turn.

So the ring does not try to track where your hand is in space. That would drift
badly within seconds. It just watches that acceleration vector spin, and asks
three questions about it:

1. Is it going round in a circle rather than back and forth? (roundness)
2. Is it staying in one flat plane rather than wobbling all over? (stability)
3. Is the circle a plausible size for a human arm? (radius)

If all three hold, the ring counts up how far around you have gone. Get about
40 percent of the way and it commits, finishing the animation on its own so you
do not have to keep circling.

The nice part is that this rejects almost everything else you do with your hands
for free. Waving is back and forth, so it fails the roundness test. Walking swings
your arm in a lazy oval, which fails the stability test. We tested against 75
seconds of hand talking, reaching and waving, plus 46 seconds of walking around an
apartment, and got zero false portals.

## Bill of materials

You only need four things.

| Part | Qty | Notes | Link |
|---|---|---|---|
| Seeed XIAO ESP32-C3 | 1 | Must be the version with the external antenna connector | https://a.co/d/0hMXK4lC |
| HW-123 (MPU-6050) IMU module | 1 | The common little purple or blue breakout board | https://a.co/d/05waVxTH |
| 120 mAh 3.7 V LiPo battery | 1 | Small enough to hide behind the boards | https://a.co/d/02xXPYqa |
| Kapton tape | 1 roll | Polyimide tape. **Regular electrical tape will do** in a pinch but is bulkier | https://a.co/d/0bSA9tBP |

## Tools

**Required**

- 3D printer
- Soldering iron
- Thin wire (30 AWG works nicely)

**Optional but recommended**

- Hot glue gun
- X-acto knife
- Multimeter (worth it, see the troubleshooting section)

## Part 1: Wire the IMU to the XIAO

Four connections. That is the whole circuit.

| MPU-6050 pin | XIAO pin |
|---|---|
| VCC | 3V3 |
| GND | GND |
| SDA | D4 |
| SCL | D5 |

Keep the wires short, just long enough that the two boards can sit back to back (might be worth supergluing the boards together (see [images](#images)).
Long wires here are the enemy, because everything has to fit inside a ring later.

Leave the AD0 pin alone. Unconnected it floats low, which sets the sensor address
to 0x68, and that is what the firmware expects.

**Before you do anything else, check your work with a multimeter.** Set it to
continuity and confirm that D5 is not connected to D6. This sounds oddly specific
because it is. See the troubleshooting section for the story.

## Part 2: Wire the battery

The XIAO has two small battery pads on its underside, marked + and minus. They
are tiny and close together, so take your time.

1. Tin both pads first with a small amount of solder.
2. Solder the red battery wire to +.
3. Solder the black battery wire to minus.

Double check the polarity before you power anything on. Backwards will damage the
board.

## Part 3: Tape it all together

1. Wrap the battery in Kapton tape. Cover the surface, but do not wrap it tight.
   A LiPo pouch cell needs a little room, and squeezing it is a bad idea.
2. Make a loop of Kapton tape, sticky side out.
3. Use that loop to stick the battery to the back side of the XIAO and IMU, so the
   whole thing becomes one small sandwich.

## Part 4: Hot glue the battery pads

Optional, strongly recommended.

Put a small blob of hot glue over the two battery pads once you have soldered
them. Those pads are small and the wires pull off very easily, usually at the
worst possible moment. The glue takes the strain instead of the solder joint.

## Part 5: Print the case

The model is in `assets/strange-ring-body-v4.3mf`.

Slicer settings:

- **Layer height:** 0.2 mm
- **Cap orientation:** upside down
- **Ring orientation:** vertical, with the finger loops pointing down (upright)
- **Supports:** on

Then remove all the supports once it comes off the bed.

PETG is a better choice than PLA here. The snap fit and the thin finger bands
will crack in PLA over time.

## Part 6: Fit the lid

The lid should slide into the body. If it does not, that is expected on a print
this small.

The tiny tabs on the USB-C port side are usually the culprit. Melt them back a
little at a time using a hot glue gun tip or an old soldering iron tip you do not
mind ruining. Test the snap fit after every pass.

Go slowly. You can always remove more material, but you cannot put it back.

## Part 7: Put the electronics in

1. Place the antenna flat in the rectangular divot in the lid.
2. Curl the antenna cable until it fits inside the cavity. You may need to tuck
   it under the electronics.
3. Do not put a sharp bend in the cable. Coax hates that, and a kinked antenna
   cable will quietly halve your Bluetooth range.
4. Test the fit.

**Take the electronics back out before you start testing.** You will be plugging
in USB, reflashing, and possibly rewiring, and all of that is far easier outside
the case. Put it in for good once the software side works.

## Images

# Top
<img width="3024" height="4032" alt="IMG_9396" src="https://github.com/user-attachments/assets/cc567806-0690-4f4f-9f41-0cdc6de72278" />

# Bottom
<img width="3024" height="4032" alt="IMG_9395" src="https://github.com/user-attachments/assets/bb30a043-feec-4169-80b0-74501fccc527" />

## Software

Work through these in order. Each step gives you something you can see working
before you build on it, which makes problems much easier to find.

### Step 0: Install

Firmware needs [PlatformIO](https://platformio.org/). The host tools need
Python 3.10 or newer.

```bash
pip install -r host/requirements.txt
```

**On Windows, run all PlatformIO commands from PowerShell or cmd, not Git Bash.**
See troubleshooting for why.

You can check the pure logic without any hardware at all:

```bash
pio test -e native        # firmware unit tests
cd host && python -m pytest tests/ -q     # detector and portal tests
```

### Step 1: Check the sensor on serial

This is the fastest way to know your soldering is good.

```bash
pio run -e xiao_serial_test -t upload
pio device monitor
```

You should see:

```
MPU-6050 ready
advertising as StrangeRing
a  -0.06  -0.07  +1.03 g   g   +0.0   -1.2   -1.1 dps   27.1 C
```

Two things to check:

- One acceleration axis reads about 1.0, the other two near 0. That is gravity.
  Tilt the board and watch which axis it moves to.
- The gyro numbers sit near zero when the board is still, and jump when you
  rotate it.

If you see `MPU-6050 init FAILED`, stop here and go to troubleshooting. Nothing
downstream will work until this line is happy.

### Step 2: Stream over Bluetooth

Now flash the normal firmware and see the data on your computer.

```bash
pio run -e xiao_esp32c3 -t upload
```

Then, from the `host` folder:

```bash
python -m portal.stream_client
```

You should see live values and a rate of about 100 Hz with `drop 0`.

The drop counter matters more than it looks. Dropped packets look exactly like
your hand holding still, so a lossy link makes the detector miss gestures and
makes it seem like the algorithm is broken when it is not.

### Step 3: Record your gesture

Now put the ring on your finger and record yourself actually using it. Record
several repetitions in one file, with a real pause in between.

```bash
python -m portal.stream_client --csv cw_short.csv --plot
```

Stand still for about 2 seconds, circle clockwise 3 times, stand still for 2
seconds, and repeat 6 or 7 times. Then Ctrl-C.

Do the same counter clockwise into `ccw_short.csv`.

The `--plot` flag writes a PNG next to the CSV. Open it. The bottom left panel is
the one to look at: your motion in its own plane. **A gesture should look like a
clean ring. If it looks like a fuzzy blob, the detector will struggle too**, and
no amount of software tuning will fix a recording that does not contain a circle.

Two things to keep constant while recording:

- Perform the gesture exactly as you plan to use it, same arm extension and same
  circle size.
- Keep the ring mounted the same way. The thresholds and the direction sense both
  depend on how the board sits on your hand.

It is also worth recording a minute of things that are **not** the gesture:
talking with your hands, reaching for things, waving, walking around. Save it as
`nearmiss.csv`. You will use it to prove the detector ignores normal life.

### Step 4: Test your recordings against the detector

```bash
python -m portal.simulate cw_short.csv
```

```
cw_short.csv   44.5 s   8 motion bursts

  PORTAL EVENTS
    time     event      took   turns   from hand starting to move
      3.37s  OPENS     1.22s   1.05   (started 2.15s)

  TIME TO OPEN: fastest 1.22s   median 1.22s   slowest 1.22s
```

Add `--timeline` for a second by second bar of what the portal is doing.

Run it on your negatives too. `nearmiss.csv` and any walking recording should
report no events at all.

### Step 5: Tune the detector if you need to

If your gestures are not detected, find out which check is failing before
changing anything:

```bash
python -m portal.live --debug
```

That adds the gate internals to the live display:

```
CLOSED [########--------------------]  29%  cw   circ 0.82 stab 0.99 r 0.19m 0.85Hz GATE
```

| Field | Needs to be | If it is failing |
|---|---|---|
| `circ` | at least 0.45 | Your circle is not round enough. Usually an oval, or too small |
| `stab` | at least 0.90 | Your hand is tilting instead of sweeping one flat circle |
| `r` | 0.09 to 0.60 m | Circle size is implausible. Tiny if barely moving, huge during an arm raise |
| `Hz` | 0.35 to 2.5 | Your spin rate |

Circle a few times and watch which number sits below its limit. Then adjust the
matching value in `DetectorConfig` in `host/portal/detect.py`.

Every threshold in that file has a comment explaining the measurement it came
from, so you can see what you are trading away.

**One warning from experience: do not tune against a recording of continuous
spinning.** A long continuous spin settles into a rhythm and reads much rounder
(0.87) than three circles from a standing start (0.63), so thresholds fitted to it
will reject your real gesture. Tune against recordings that look like how you
will actually use it.

### Step 6: Run the portal live

```bash
python -m portal.live
```

Circle clockwise and watch it open. Drop your hand and it stays open. Circle
counter clockwise to close it.

```
OPEN   [############################] 100%  cw    99.8Hz drop 0
[   4.13s]  PORTAL OPEN   (was CLOSED for 4.1s)
```

Add `--csv session.csv` to record while you play, which is handy for debugging a
gesture that did not work.

This is the signal that drives the visuals. It is a single number from 0 to 1 plus
a direction, which is deliberately simple so you can hook it to whatever you like.

## Troubleshooting

### `MPU-6050 init FAILED`, or no I2C at all

Work through these in order.

1. **Check for a solder bridge between D5 and D6.** This one cost us a full day.
   D6 is the UART transmit pin, and it is a push-pull output, while I2C needs the
   clock line to be open drain. A bridge means the UART holds your clock line
   down and the sensor never sees a usable clock. A continuity test found it
   reading 0 ohms in about 10 seconds.
2. **Use a continuity test, not voltage measurements.** We tried to detect that
   bridge by driving the pins and measuring voltage, and got a false negative,
   because when two CMOS outputs fight each other the low side wins and the node
   just reads 0 V either way. Two drivers fighting do not meet in the middle.
   Probe for continuity directly.
3. Check continuity from each XIAO pin to the matching IMU pin.
4. Check that AD0 is floating or grounded, not pulled high.
5. Confirm you wired VCC to 3V3 and not 5V.

### `pio run` fails with `riscv32-esp-elf-g++: not found`

You are in Git Bash. Espressif's toolchain installer refuses to install under
MSYS or MinGW, so the compiler never gets set up.

Run the same command from PowerShell or cmd and it works. The `native` test
environment is fine from any shell.

### `error: no device named StrangeRing found`

- Check the ring is powered. Plug in USB and watch the serial monitor.
- Charge the battery.
- Get closer. A curled or kinked antenna cable cuts range badly.
- Make sure another program is not already connected to it.
- If you painted the case, see below.

### Drop counter climbing, or rate well below 100 Hz

Gaps in the stream look identical to your hand being still, so gestures get
missed. Move closer to the computer, check the antenna is seated in its divot,
and confirm the cable is not sharply bent.

Do not train or tune the detector on a recording with heavy loss. It will teach
the detector the wrong thing.

### The portal never opens

Run `python -m portal.live --debug` and see which gate is refusing, using the
table in Step 5. In our experience `circ` is the one most likely to be marginal.

### Open and close are backwards

Change `OPENING_SENSE` in `host/portal/simulate.py` from `-1` to `1`.

This sign is tied to how the ring is physically mounted, since it comes from
which way the rotation axis points in the sensor's own frame. Flip the board over
and the sense flips with it.

### It worked, then stopped after I put it in the case

The thresholds and the direction sense are both specific to how the board is
mounted. Moving the electronics changes the gravity vector and can flip the
direction sense.

Record a fresh `cw_short.csv` in the final mounted position and re-check with
`python -m portal.simulate`. This is also why we recommend testing outside the
case first, so you know the electronics work before adding a variable.

### Slow circles do not register

This one is physics rather than a bug. Centripetal acceleration scales with the
square of speed, so halving your speed gives you a quarter of the signal. At
around 0.5 turns per second the signal is only about 0.19 g and the natural
tremor in your arm starts to dominate.

Circle at a natural pace, somewhere around 0.7 to 1.1 turns per second.

### The battery wires keep breaking off

Hot glue over the pads. See Part 4. This will happen eventually if you skip it.

### Battery drains fast even when idle

The HW-123 module has a power LED that is always on, burning 3 to 5 mA
continuously. That is a large fraction of a 100 mAh battery.

Find the small series resistor next to the LED and remove it. The sensor does not
care.

### The lid will not snap in

Melt the tabs on the USB-C side back a little at a time. See Part 6. Small print,
tight tolerances, entirely normal.

### Tests pass but say `skipped`

The golden tests skip when the CSV files are missing rather than failing. If you
cloned this without the recordings, record your own using Step 3 and name them to
match, or ignore those tests and rely on the synthetic ones.

### I painted the case and now the range is bad

Some metallic paints are conductive enough to shield the antenna. Check across
about 1 cm of the painted surface with a multimeter. An open circuit or megohms
is fine. Anything low is a problem.

Flake in resin metallic paints are usually fine. True chrome paint and shielding
paint are not.

## Repo layout

```
src/main.cpp              firmware: read the sensor, stream over Bluetooth
lib/mpu6050/              sensor registers and scaling, unit tested
lib/protocol/             the wire format, shared with the Python side
test/                     firmware unit tests, run with pio test -e native

host/portal/detect.py     the detector: motion in, openness out
host/portal/simulate.py   the portal state machine: open, closed and latching
host/portal/live.py       live portal driven from the ring over Bluetooth
host/portal/stream_client.py   connect, display and record
host/portal/plot.py       turn a recording into a diagnostic plot
host/tests/               detector and portal tests, including golden tests

assets/                   the printable case
```

## A note on what is in here

The detector reads only the accelerometer. The gyroscope is wired and streamed,
but nothing uses it.

That was not the original plan. The design assumed you would hold your wrist
rigid, so a large gyro reading would be good evidence that the motion was *not*
the gesture. Then we measured it, and found 108 to 118 degrees per second of
wrist rock during a perfectly good gesture. That check would have rejected the
real thing every time, so it was cut.

There are a few more of these documented in the code comments, where a threshold
or a design choice is explained by the measurement that produced it rather than by
what seemed sensible at the time. If you are adapting this, those comments are the
most useful thing in the repo.

## License

MIT. Build it, change it, put it in a video.

# Dr. Strange Sling Ring

A wearable sling ring that opens a portal when you draw a circle in the air, and
closes it when you draw one the other way. No buttons, no phone, no cameras
watching your hand. Just a motion sensor on your finger and a bit of signal
processing.

Circle counter clockwise and the portal opens. Circle clockwise and it closes,
the way Strange does it on screen.
It takes about one and a half turns, roughly 1.2 seconds, and it stays open
after you drop your hand.

Everything here is open source. The electronics are three parts, the case prints
in one go on any hobby printer, and the whole thing runs on a battery the size of
a postage stamp.

The portal itself is a fullscreen window on a second display, meant to be thrown
onto a wall by a projector, with a live camera feed showing through the middle of
the ring. Steps 7 to 10 cover that half.

There are **two rings**. The main one, on your gesture hand, holds the motion
sensor and does everything described above. The second is a *key ring* worn on
the other hand with a capacitive touch pad: the portal ignores the circle
gesture unless the key is armed, so nobody opens a portal by accident. It is a
separate board with separate firmware, covered in Step 2b, and the whole system
runs happily without it if you skip that step.

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

The key ring adds one more condition on top, but not a clever one: the portal
simply ignores every sample while the key is disarmed. The detector keeps
running underneath, so an armed gesture starts from a warm filter rather than a
cold one.

The nice part is that this rejects almost everything else you do with your hands
for free. Waving is back and forth, so it fails the roundness test. Walking swings
your arm in a lazy oval, which fails the stability test. We tested against 75
seconds of hand talking, reaching and waving, plus 46 seconds of walking around an
apartment, and got zero false portals.

## Bill of materials

Four things for the main ring.

| Part | Qty | Notes | Link |
|---|---|---|---|
| Seeed XIAO ESP32-C3 | 1 | Must be the version with the external antenna connector | https://a.co/d/0hMXK4lC |
| HW-123 (MPU-6050) IMU module | 1 | The common little purple or blue breakout board | https://a.co/d/05waVxTH |
| 120 mAh 3.7 V LiPo battery | 1 | Small enough to hide behind the boards | https://a.co/d/02xXPYqa |
| Kapton tape | 1 roll | Polyimide tape. **Regular electrical tape will do** in a pinch but is bulkier | https://a.co/d/0bSA9tBP |

Three more if you also want the key ring from Step 2b. Skip these and
everything still works; you just lose the arming gate.

| Part | Qty | Notes |
|---|---|---|
| Seeed XIAO ESP32-C3 | 1 | A second board, flashed with different firmware |
| TTP223 capacitive touch breakout | 1 | The common single-pad module, three pins |
| 3.7 V LiPo battery | 1 | Same as above |

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

### Top
<img width="3024" height="4032" alt="IMG_9396" src="https://github.com/user-attachments/assets/cc567806-0690-4f4f-9f41-0cdc6de72278" />

### Bottom
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
pio run -e portal_ring_serial -t upload
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
pio run -e portal_ring -t upload
```

Then, from the `host` folder:

```bash
python -m portal.stream_client
```

You should see live values and a rate of about 100 Hz with `drop 0`.

The drop counter matters more than it looks. Dropped packets look exactly like
your hand holding still, so a lossy link makes the detector miss gestures and
makes it seem like the algorithm is broken when it is not.

### Step 2b: The key ring

A second, completely separate XIAO ESP32-C3 worn on the other hand acts as a
key. The portal only responds to the circle gesture while the key ring is
armed, so a stray circle drawn without it does nothing. It is its own board,
its own firmware, and its own Bluetooth connection.

| TTP223 pin | XIAO pin | Notes |
| --- | --- | --- |
| VCC | D9 | Driven high by the firmware, not tied to the 3V3 rail |
| IO | D10 | Touch output |
| GND | GND | |

VCC goes to a GPIO rather than the 3V3 rail for historical reasons, explained
in the limitation below. The firmware holds it high and never lets go.

```bash
pio run -e touch_ring -t upload
pio device monitor
```

Touch the pad. You should see `ARMED`, and `DISARMED` when you let go.

#### Known limitation: the pad disarms itself after 7 seconds

The TTP223 detects *changes* in capacitance, not the presence of a finger, and
it re-baselines its own reference roughly every 7 seconds. We measured that on
this ring rather than trusting the datasheet, using the timestamps the firmware
prints. Hold the pad longer than that and your finger becomes the new
"untouched" zero, so the output reads released while you are still touching it.

**The practical effect is that a touch arms the key ring for about 7 seconds,
then it drops on its own.** That is fine in use, because the gesture takes
about 1.2 seconds: touch the pad, draw the circle, done. But this ring cannot
report sustained *wear*, and no firmware can see through it, because the
baseline lives inside the chip.

Two ways out if it ever matters, neither of them taken here:

- **Toggle mode.** Bridging the solder pad marked `A` on the back of the
  breakout straps the chip into a mode where the output latches on each touch
  and holds indefinitely. Tap to arm, tap to disarm. The cost is that it stops
  tracking whether the ring is actually on your finger at all.
- **Skin contact.** Replace the TTP223 with two bare metal contacts on the
  inside of the ring and read the resistance through your finger, somewhere
  around 100 k to 1 M ohm. That measures presence directly, has no baseline to
  drift, and is fewer parts than the breakout.

One approach that does **not** work, in case it looks tempting: cutting the
sensor's power to force it to re-calibrate. That is why VCC sits on a GPIO. It
fails because re-calibrating while the pad is touched makes the touched state
the new zero, so the sensor then reports "not touched" permanently. It destroys
the signal it was meant to protect.

#### Using it

Both host tools gate on the key ring, and both take `--no-key` to run without
it:

```bash
python -m portal.live              # shows KEY / ---- beside the portal state
python -m portal.render --ring     # key state in the on-screen status line
```

Two behaviours are deliberate. The gate **fails closed**: no key connection
means disarmed, because a ring that cannot be heard from is not a ring being
worn. And disarming **holds an open portal** rather than slamming it shut, so a
dropped Bluetooth packet cannot cut the portal out of a take.

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

Circle counter clockwise and watch it open. Drop your hand and it stays open.
Circle clockwise to close it.

```
OPEN   [############################] 100%  cw    99.8Hz drop 0
[   4.13s]  PORTAL OPEN   (was CLOSED for 4.1s)
```

Add `--csv session.csv` to record while you play, which is handy for debugging a
gesture that did not work.

This is the signal that drives the visuals. It is a single number from 0 to 1 plus
a direction, which is deliberately simple so you can hook it to whatever you like.

### Step 7: The portal animation

The renderer does not draw the portal from scratch. It takes a video of one and
puts your camera feed in the middle of it.

**The clip is already in `assets/`, and every default is tuned to it.** You do
not need to find one, trim it, or work out where anything starts and ends. The
frame numbers in the next step are the ones this file wants, so Step 8 should
work the moment you run it.

The file is a stock green screen pack by Filmcom Creation, included here so the
build is reproducible. It holds the same 341-frame animation three times over,
on black, on green and on blue, and the renderer picks the black take by itself
by looking at frame corners.

**Why the black take and not the green one.** Fire is additive light with no
hard edge, so a chroma key has to invent a coverage value for every wispy spark,
and green spill contaminates orange worse than any other colour pairing. The
black take is the element as it was originally rendered, so screen blending it
reproduces the intended composite exactly, with no matte estimation anywhere. It
also keeps the area outside the ring at true black, which matters in Step 10.

If you swap in a different clip, pass it with `--clip` and expect to re-derive
the section boundaries in Step 8; they are properties of this particular
animation, not of portals in general.

### Step 8: See the portal on screen

```bash
cd host
python -m portal.render --stats
```

The first run reads the clip, finds the black take, measures the ring's rim on
every frame and caches all of it next to the video. That takes about 20 seconds.
Every run after it starts in well under a second.

You should get a window with your webcam inside the ring. Drive it by hand:

```
  a / d   scrub the portal closed / open      space  auto open-close
  f       toggle fullscreen                    q      quit
```

Three things are happening in that window, and only two of them are "playing".
These are the defaults, already set for the clip in `assets/`:

| Phase | Frames | Flag | Driven by |
|---|---|---|---|
| opening | 0 to 107 | `--open-end` | your hand, rate-limited to the clip's own speed |
| sustain | 165 to 219 | `--loop-start`, `--loop-end` | time, looping until you close it |
| closing | 248 to 340 | `--shrink-start`, `--close-end` | time, at 2.5x |

None of those numbers were picked by eye. The loop bounds come from scoring
every pair of frames in the clip and taking the pair whose motion matches best;
the closing starts at 248 because that is the first frame where the ring's
radius actually falls, having sat at 286 to 288 pixels for the thirty frames
before it.

The sustain loop jumps from frame 219 straight back to 165 with no blending.
Those two frames differ about as much as any two consecutive frames do, so the
cut hides inside motion your eye already absorbs 24 times a second. The glow
eases across over 8 frames while the sparks hard-cut, because dissolving two
different spark patterns reads as a double exposure and measured *worse* than
doing nothing.

If you do not have the ring built yet, you can drive the whole thing from one of
the captures you recorded in Step 3:

```bash
python -m portal.render --replay ccw_short.csv
```

### Step 9: Drive the portal from the ring

```bash
python -m portal.render --ring --camera http://<phone-ip>:8081/video --stats
```

Counter-clockwise opens it, clockwise closes it, and a hand that stops leaves it
where it is. If you built the key ring in Step 2b, touch its pad first: the
gesture does nothing while the key is disarmed. Add `--no-key` to bypass it.

`--stats` puts both Bluetooth connections in the on-screen status line, which is
what you want on a first run. You can confirm `key ARMED` and `ring connected`
before you start circling, instead of guessing which half is broken. Drop it
when you actually film.

Power both rings before launching. The two connections are scanned for on
separate threads, so you will see two "waiting for..." lines, and either can
connect first. This is the same detector and the same state machine `portal.live`
prints to the terminal, so anything you tuned in Step 5 applies here unchanged.

Expect roughly two seconds between starting to circle and the portal beginning to
draw. Most of that is the detector building confidence: the gate alone averages
over a full carrier period before it will vote.

### Step 10: Put it on a projector

Filming this off a projector onto a wall looks far better than filming a screen,
and it is the reason for a lot of the choices in the renderer.

Plug the projector in and set Windows to **Extend**, not Duplicate. Then find it:

```bash
python -m portal.render --list-displays
```

```
  --display 0   1440x900 at (0, 0) (primary)
  --display 1   1920x1080 at (1440, 0)
```

```bash
python -m portal.render --ring --fullscreen --display 1
```

That gives you a borderless fullscreen portal with no title bar and no overlay.
Leave `--stats` off when you film, and park the mouse pointer on the laptop
screen so it does not sit in the projection.

**A projector cannot emit black.** It can only stop adding light, so anywhere the
image is not perfectly zero, the projector paints a faintly grey 16:9 rectangle
on your wall. This is why the renderer screen blends instead of keying, and why
it subtracts a small black level from every frame: the clip's "black" background
is not actually black, and 26 percent of its corner pixels sit at value 1. If you
still see a rectangle in a dark room, raise `--black-floor` until it goes, at a
small cost in picture quality.

### What the portal looks onto

By default the disc shows your laptop webcam. Anything OpenCV can open works:

```bash
python -m portal.render --camera 1                              # another webcam
python -m portal.render --camera http://192.168.1.42:8081/video # a phone
python -m portal.render --camera clips/other_room.mp4           # a recording
```

For a phone, either turn on Windows 11's "use as a connected camera" and pass its
index, or install an IP-webcam app and pass the URL it gives you. Any app that
serves MJPEG over HTTP works; these are the usual ones:

| Phone | App | Typical URL |
|---|---|---|
| iOS | **IP Camera Lite** (Shenyao Ke) | `http://<phone-ip>:8081/video` |
| Android | **IP Webcam** (Pavel Khlebovich) | `http://<phone-ip>:8080/video` |

**Only the iOS side is actually tested here**, because that is the phone we
have. Android should work exactly the same way — it is a plain MJPEG stream over
HTTP either way, and OpenCV does not care which phone produced it — but treat
the Android row as untested.

Two things to watch, both of which cost us time:

- **The port and path are not the same between apps.** Note that IP Camera Lite
  uses 8081 while IP Webcam uses 8080. Whatever the app shows on its own screen
  is the address of a *web page*, not necessarily the raw stream; the stream is
  usually that address with `/video` on the end.
- **Turn the app's password off**, or put the credentials in the URL. IP Camera
  Lite asks for an HTTP login by default, and a browser hides this from you by
  remembering the password after the first time. OpenCV sends no credentials and
  simply gets refused. See the troubleshooting entry on colour bars.

Both phones need to be on the same network as the laptop. A phone hotspot the
laptop is joined to works fine, and is often easier than getting two devices onto
the same guest Wi-Fi.

A stream that stalls will not freeze the portal: the camera is read on its own
thread and the animation runs on the clock, so a slow feed just repeats a frame.

Two things decide whether this reads as a hole in space or as a video window.
**Point the camera somewhere the projection cannot reach**, or it films the wall
it is being projected onto and you get feedback. And **the destination needs to be
brighter than the room you are filming in**, or the disc reads as a grey patch.

`--no-mirror` turns off the left-right flip, which you probably want for anything
that is not a view of yourself.

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

First check the key ring, if you built one. `python -m portal.live` shows `KEY`
when armed and `----` when not, and the portal ignores your hand entirely while
it reads `----`. The gate fails closed on purpose, so a key ring with a flat
battery, or one that never connected, looks exactly like a dead gesture
detector. `--no-key` takes it out of the picture and tells you which half you
are actually chasing.

Remember the pad disarms itself about 7 seconds after you touch it. Touch,
then circle; do not touch and then think about it.

Then run `python -m portal.live --debug` and see which gate is refusing, using
the table in Step 5. In our experience `circ` is the one most likely to be
marginal.

### `error: no device named StrangeKey found`

The key ring is not advertising. Same checklist as the `StrangeRing` entry
above: check it is powered, and that nothing else is already connected to it,
because a BLE peripheral accepts one connection at a time.

If you are running both `portal.live` and `portal.render` at once, that is the
problem. They each open their own connection to both rings, and the second one
to start will not get in.

### The key ring arms, then disarms on its own after a few seconds

Expected, and a hardware limitation of the TTP223 rather than a bug. It
re-baselines its capacitance reference roughly every 7 seconds, so a held touch
becomes the new "untouched" zero. Step 2b explains it and lists the two ways
out if you need sustained wear detection.

### The camera feed is colour bars, but the URL works in my browser

Almost certainly authentication. Some phone webcam apps require an HTTP login,
and your browser has the password saved from the first time you opened it;
OpenCV sends no credentials and gets refused. IP Camera Lite on iOS does this by
default. You can check from the command line:

```bash
curl -s -D - -o /dev/null http://<phone-ip>:8081/video
```

`401 Authorization Required` confirms it. Either turn the password off in the
app, or put the credentials in the URL:

```bash
python -m portal.render --ring --camera "http://user:pass@<phone-ip>:8081/video"
```

The other common cause is the wrong path or port. The address that shows you a
*page* in the browser is not the raw video stream. `/video` is the usual
endpoint; some apps use `/videofeed`, `/live` or `/mjpeg`. IP Camera Lite serves
on 8081 and IP Webcam on 8080, so do not copy a port from one app's docs into
the other's URL.

### Open and close are backwards

Change `OPENING_SENSE` in `host/portal/simulate.py` from `1` to `-1`.

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

### `no .mp4 found in assets/`

The clip ships in `assets/`, so this usually means a partial clone or a checkout
that skipped binaries. Pull it again, or point `--clip` at a copy elsewhere.

### `no black-background section found`

The clip you passed with `--clip` only has the green or blue take. The renderer
will not key it: see Step 7 for why. Use the one in `assets/`, or composite your
green version onto black once in an editor and export that.

### A different clip opens or closes at the wrong moment

The frame numbers in Step 8 describe the animation in `assets/`, not portals
generally. For another clip, step through it and find three things: the frame
where the arc finishes drawing (`--open-end`), a pair of frames in the steady
part that look alike enough to cut between (`--loop-start`, `--loop-end`), and
the first frame where the ring genuinely starts shrinking (`--shrink-start`).

### A faintly lit rectangle on the wall

The projector is being told to emit something everywhere, not nothing. Raise
`--black-floor` a couple of levels at a time until it goes. It defaults to 2,
which is enough for the clip we tested; a noisier export may need more.

If it persists at a high floor, check the projector's own brightness and contrast
settings, which sometimes lift blacks on their own.

### The webcam runs at about 5fps

You are on the DirectShow backend. On the laptop we tested, DirectShow delivers
1080p at 5fps and 720p at 10fps from a camera that does 1080p at 31fps through
Media Foundation. Do not pass `--dshow`; it exists only as a fallback.

### The opening looks choppy, but the loop and the close are smooth

Openness arrives with the Bluetooth packets, about ten times a second, while the
renderer draws forty or more. `--open-smoothing` fills in the frames between
updates and defaults to 0.05 seconds. If you have set it to 0, put it back.

### The opening looks sped up

`--open-speed` caps how fast the arc may draw, as a multiple of the clip's own
rate. At 1.0, a quick gesture hands over and the animation finishes itself at the
speed it was animated. Raising it lets a fast gesture drag the animation along
faster, which is snappier but blurs the spark trace.

### The camera feed stops short of the rim

`--fill` sets how far the feed reaches toward the ring, as a fraction of the rim
radius. It defaults to 0.98, which tucks the edge just under the brightest part
of the rim so the ring's own light hides the seam. Lower it and a dark band
opens up, which reads as a video window rather than a hole.

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
src/portal_ring/main.cpp  firmware: read the sensor, stream over Bluetooth
src/touch_ring/main.cpp   firmware for the key ring: touch pad, armed byte
lib/mpu6050/              sensor registers and scaling, unit tested
lib/protocol/             the wire format, shared with the Python side
test/                     firmware unit tests, run with pio test -e native

host/portal/detect.py     the detector: motion in, openness out
host/portal/simulate.py   the portal state machine: open, closed and latching
host/portal/live.py       live portal driven from the ring over Bluetooth
host/portal/stream_client.py   connect, display and record
host/portal/plot.py       turn a recording into a diagnostic plot
host/portal/ring.py       openness for the renderer: from the ring, or replayed
host/portal/render.py     the portal itself: camera in the ring, ring on top
host/tests/               detector and portal tests, including golden tests

assets/                   the printable case, and the portal clip
```

The clip in `assets/` is a stock green screen pack by Filmcom Creation, included
so the defaults in `render.py` line up with something you actually have. It is
theirs, not ours; if you are reusing this repo for something you intend to
publish, check their terms rather than assuming this repo's licence covers it.

Both firmwares live in one PlatformIO project and are told apart by
`build_src_filter`, so each environment compiles only its own folder under
`src/` and the two boards can never accidentally share code. `lib/` is shared
by both. The environments are:

| Environment | Board | What it does |
|---|---|---|
| `portal_ring` | gesture ring | The real firmware: IMU over Bluetooth |
| `portal_ring_serial` | gesture ring | Same, plus live sensor values on serial for bring-up |
| `touch_ring` | key ring | Touch pad state as one byte over Bluetooth |
| `native` | your computer | Firmware unit tests, no hardware needed |

The split between the last two host modules is the useful one. `render.py` knows
nothing about Bluetooth or gestures; its entire input is one number between 0 and
1. `ring.py` is what produces that number, from the ring or from a recording.
Either can be replaced without touching the other.

## A note on what is in here

The detector reads only the accelerometer. The gyroscope is wired and streamed,
but nothing uses it.

That was not the original plan. The design assumed you would hold your wrist
rigid, so a large gyro reading would be good evidence that the motion was *not*
the gesture. Then we measured it, and found 108 to 118 degrees per second of
wrist rock during a perfectly good gesture. That check would have rejected the
real thing every time, so it was cut.

The renderer has the same shape. The loop points are not chosen by eye: every
pair of frames in the clip was scored, and frame 219 goes back to 165 because
those two differ about as much as any two consecutive frames do. The black level
is 2 because 26 percent of the clip's corner pixels sit at value 1 and only
0.017 percent exceed 2. The sparks hard-cut across the loop seam while the glow
dissolves, because blending both measured worse than blending neither.

The key ring is the same story told backwards, and it is worth reading Step 2b
even if you never build one. The plan was to power the touch sensor from a GPIO
and cut it briefly once a second, forcing the chip's auto-calibration to happen
at a moment we controlled. It cannot work, and measuring is what showed why: the
TTP223 senses *change*, not presence, so re-calibrating while the pad is touched
adopts the touched state as its new zero. Power cycling would have made the
sensor report "not worn" permanently. The pin is still a GPIO, held high forever,
as a fossil of the idea.

What shipped instead is the plain sensor with its 7-second limitation documented
rather than engineered around, because the gesture takes 1.2 seconds and 7 is
enough. The two real fixes, toggle mode and skin contact, are written up in Step
2b for anyone who needs sustained wear detection.

There are a few more of these documented in the code comments, where a threshold
or a design choice is explained by the measurement that produced it rather than by
what seemed sensible at the time. If you are adapting this, those comments are the
most useful thing in the repo.

## License

MIT. Build it, change it, put it in a video.

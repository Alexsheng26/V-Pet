# v-pet

**A desktop pet that lives on your Windows taskbar.** Frameless, always-on-top,
per-pixel alpha. Throw it across the screen, stick it flat against the screen edge,
let it walk along the title bars of your open windows. 65 MB portable, 1.2 s cold start.

[![CI](https://github.com/Alexsheng26/V-Pet/actions/workflows/ci.yml/badge.svg)](https://github.com/Alexsheng26/V-Pet/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.10%2B-3776ab) ![tests](https://img.shields.io/badge/tests-181-brightgreen) ![deps](https://img.shields.io/badge/runtime%20deps-PySide6%20only-blueviolet) ![license](https://img.shields.io/badge/license-MIT-green)

![demo](docs/demo.gif)

> **The GIF is not hand-animated.** `tools/make_demo.py` drives the *real* `PetBrain` —
> gravity, the bounce coefficient, the impact threshold that decides whether it gets
> dizzy, the probability of folding its arms are all production code. The script only
> feeds it user input ("grab", "release", "pat") at scripted moments, so what you see
> is what the program actually does. The generator self-checks: every state has to show
> up and the landing impact has to genuinely cross the dizzy threshold, or it exits non-zero.
>
> The **GIF encoder is hand-written too** (`tools/gif.py` — median-cut palette, LZW,
> inter-frame diffing). Qt can *read* GIF but not write it, the standard library has no
> encoder, and pulling in Pillow for a single documentation asset wasn't worth it.

**中文文档（更详细）→ [README.md](README.md)**

---

## Run it

```bash
pip install -r requirements.txt
python main.py
```

No asset files needed — the character is drawn with `QPainter` at runtime.
For a portable build that doesn't need Python, see [Releases](https://github.com/Alexsheng26/V-Pet/releases).

## What it does

| Do this | It does that |
|---|---|
| Drag and fling it | Falls with the velocity you threw it at, bounces on landing |
| Throw it hard enough | Gets dizzy, stars circling overhead |
| Drop it near a screen edge | **Lies flat against the wall**, braced with both hands, slowly sliding down |
| Drop it above a window | Stands on the title bar. Move the window and it rides along; close it and it falls |
| Drop it on a desktop icon | Tilts its head at it with a question mark |
| Double-click, or rub the cursor over it | Head pat |
| Leave it alone | Wanders, folds its arms, eventually falls asleep |
| Right-click / tray | Follow the cursor, resize, run at startup, quit |

Position, size, follow toggle and autostart persist across restarts.

## The interesting part: a desktop pet is a windowing problem

The pet logic is a few hundred lines of state machine. Everything that actually
took a while is about the *window*.

### Per-pixel transparency, not colour keying

`FramelessWindowHint` + `WA_TranslucentBackground` gives a real alpha channel, so the
character has antialiased edges, a semi-transparent drop shadow, and effects that fade
in and out.

The alternative — tkinter's `-transparentcolor` — is **colour keying**: it can only knock
out one flat colour, so edges are hard and fringed and semi-transparent shadows are
impossible. That limit is unavoidable eventually, and migrating after hitting it means
rewriting the whole render layer, so the PySide6 dependency was paid up front.

### Click-through: a square window holding a round pet

The window is a 144×144 square; the pet is round. If the fully transparent corners
still swallow mouse events, the pet becomes an invisible sheet of glass over your
desktop icons.

Qt can only toggle `WA_TransparentForMouseEvents` for the *whole* window, so this drops
down to Win32 and toggles `WS_EX_TRANSPARENT` per frame based on the alpha of the pixel
under the cursor. The non-obvious part: **once `WS_EX_TRANSPARENT` is set the window
receives no mouse events at all**, so there is no `enterEvent` to tell you the cursor
came back — the only way is polling the global cursor position.

The hit test reuses the alpha of the current frame, which is why the render layer returns
a `QImage` instead of painting straight onto the widget. The "rub to pat" gesture rides
on the same poll: that loop already knows whether the cursor is on the pet's body, so it
only has to accumulate cursor movement.

### Multi-monitor: the boundary is not a rectangle

With one screen the boundary *is* a rectangle. With several, that model breaks:

- the seam between two screens **is not a wall** — the pet should walk across it
- screens can differ in height, so **the floor level changes at the seam**
- screens can be offset, so there are **dead zones with no screen at all**

The obvious approach — take the bounding box of all screens — is wrong: the pet walks
into a dead zone and vanishes while the process and tray icon are still there. So
`screens.py` keeps each screen's rectangle and answers "can I keep walking that way?"
per screen.

Crossing is decided by the pet's **centre** passing the seam, not by the whole window
leaving the screen; the latter stops it a body-width short and it never reaches the seam.
A floor-level difference of more than 12 px at the seam turns into a fall with horizontal
velocity preserved; less than that is just a step up. Edge-clinging only engages on sides
with no neighbouring screen, otherwise the pet hangs in the middle of a dual-monitor desktop.

Screen configuration changes are detected by comparing a fingerprint rather than by
wiring up `screenAdded` / `availableGeometryChanged` — a newly plugged-in screen would
need its own signal connected, and missing one is a silent wrong state.

### Reading the desktop: three things the docs won't tell you

The pet can stand on window title bars and recognise the desktop icon underneath it.
Both need data from Windows, and all three of these bite:

**Use `DwmGetWindowAttribute(EXTENDED_FRAME_BOUNDS)`, not `GetWindowRect`.** The latter
includes the invisible Aero shadow border — seven or eight pixels on each side — so the
pet stands on thin air next to the window's visible edge. It is obvious on sight.

**`IsWindowVisible` does not filter out UWP ghost windows.** They report as visible but
are hidden by DWM; only `DWMWA_CLOAKED` identifies them. On my machine 6 of 8 "visible"
top-level windows were ghosts — without the check the desktop grows a row of ledges that
correspond to nothing.

**Desktop icons belong to explorer.exe, and `LVM_GETITEMRECT` wants the result written
into *that* process's address space.** Passing a pointer from your own process just
returns zeros. You have to `OpenProcess` + `VirtualAllocEx` inside explorer, send the
message, and `ReadProcessMemory` it back. If any of that fails it returns an empty list —
this is a garnish, not something worth crashing the pet over.

Two more rules came out of measurement rather than reasoning: a maximized window's top
edge is at y=0 and the pet would stand entirely off-screen, so ledge queries take a
"ceiling" argument; and a moving window is matched **by handle, not by position** —
requiring the pet to still be within the new bounds meant slow drags worked but a
`Win+←` snap dropped it.

Polling rates were measured, not guessed: enumerating windows costs 0.2 ms so it runs
every 100 ms; enumerating icons costs 1.6 ms (~10% of a frame budget) so it runs **once,
on mouse release**, and never in the frame loop.

### Crashes have to leave something behind

A `console=False` window application **has no stderr anyone can read**. An uncaught
exception looks exactly like "the pet vanished" — tray icon gone, window gone, nothing
left. The user can't report *how* it broke and you can't diagnose it. That's worse than
the crash itself.

So `crashlog.py` writes the traceback plus version, platform and frozen-state to
`%APPDATA%\v-pet\crash.log`, and the window layer raises a tray notification pointing
at the file.

Two details came out of measurement:

- **An exception in a Qt slot does not terminate the program.** PySide6 6.11 calls
  `sys.excepthook` and the event loop keeps going — and the main loop runs at 60 fps,
  so one bug writes 60 log entries per second. Deduplication is **required, not an
  optimisation**, and the loop stops its own timer as well, otherwise the same bug
  keeps firing sixty times a second.
- **A crash handler must never throw.** `record()` is wrapped end to end and returns
  `None` on a full disk or a permissions error. A crash handler that crashes is worse
  than none.

#### Two pets overwrite each other's config

Double-click the exe twice and you get two pets — **writing the same `config.json`**.
Position, size and toggles clobber each other and whoever quits last wins. With autostart
enabled, opening it manually once is enough to hit this, which is the most likely case.

This uses a **named mutex** rather than a lock file: however the process dies — crash,
Task Manager, power cut — the system releases it. A lock file survives all of those and
leaves a program that **can never start again**, which is worse than no guard at all.

The second instance doesn't exit silently; it **broadcasts a custom window message** so
the running one shows itself. Otherwise the user sees "double-clicking does nothing",
especially when the pet is currently hidden.

The handler has to be **idempotent**: `HWND_BROADCAST` is delivered to *every* top-level
window in the process, including Qt's hidden helper windows — measured, one broadcast
arrives five times.

### Architecture

```
vpet/state.py      behaviour: state machine + physics.   no Qt imports
vpet/screens.py    multi-monitor geometry: seams, dead zones, adjacency.  no Qt imports
vpet/ledges.py     standable surfaces: landing, following a moving window. no Qt imports
vpet/config.py     persistence.                          no Qt imports
vpet/crashlog.py   uncaught exceptions -> a log file.    no Qt imports
vpet/instance.py   single-instance guard (named mutex)
vpet/render.py     state -> QImage, plus a character-agnostic pose system
vpet/window.py     transparency, always-on-top, dragging, click-through, tray
vpet/desktop.py    Win32: enumerate window edges and desktop icons
tools/             docs generation, icon generation, packaging
tests/             181 tests, 134 of which need no Qt at all
```

Three seams, all so that changing one side doesn't touch the other:

**Behaviour ⊥ Qt.** `state.py`, `screens.py` and `ledges.py` don't draw a single pixel.
The payoff is that gravity, edge-cling thresholds and throw-velocity limits are unit
testable without a GUI — change a feel parameter and verify it immediately.

**Pose ⊥ character.** `pose_for()` only says how a state squashes, stretches, offsets and
rotates. Swap the character and the animation comes along for free.

**Render ⊥ assets.** The window asks a provider for "the current frame" and doesn't care
whether it came from a PNG or was drawn just now. The `State` enum values *are* the
directory names, so dropping PNGs into `sprites/{idle,walk,…}/` reskins it without a
code change.

### The CI job that matters

CI runs the suite on Windows across Python 3.10 / 3.13 / 3.14, packages the exe and
publishes releases. The job worth pointing at is a different one:

**An architecture guard on Linux that deliberately does not install PySide6**, and runs
the 111 tests that claim not to need it. The README above claims those layers are Qt-free
and OS-free; left to good intentions, that claim eventually breaks on some "it's just one
`QPoint`" afternoon — and **running the full suite on Windows would never catch it**.
The job also asserts up front that PySide6 really is absent, so the guard can't quietly
become decorative.

## Bugs only the tests caught

None of these were crashes. They all looked like working software.

**The pet could never fall asleep.** `_tick_walk` reset the idle timer every frame, and
idle switches to walk every 1–4 s, so the 30 s threshold was unreachable. The semantics
were confused: what should reset the timer is *the user interacting*, not the pet taking
a stroll. You can't spot this by watching the window — you have to wait out the full 30 s
and notice that nothing happens.

**The character was clipped on high-DPI displays.** `render()` called `p.scale(dpr, dpr)`,
but a `QPainter` on a `QImage` that has `devicePixelRatio` set **already applies that
scale**. Invisible at 100% (dpr=1), clipping at 150%. The regression test renders at
dpr = 1.0 / 1.5 / 2.0 and compares the bounding box in *logical* coordinates: the physical
pixel count should change, the logical size should not.

**Hearts were clipped at the top of the canvas.** The awkward part is that **a bounding
box cannot detect clipping** — the clipped part doesn't make the box bigger, it just makes
it stop at 0. So the assertion has to be "at least half a pixel of margin from the edge",
inferring clipping from the absence of slack. Adding it immediately caught a second case.

**The hand-written GIF decoded to noise after the first few pixels.** The LZW code width
was widened one code too early. The reason is unintuitive: **the decoder builds its
dictionary one step behind the encoder**, so widening on the encoder's own `next_code`
desynchronises them for exactly one code — encoder writes n+1 bits, decoder reads n.
The only trustworthy check was round-tripping through an independent decoder, and Qt's
GIF reader (read-only, so it can't share the bug) made a good referee.

**6.8 MB of OpenSSL shipped in v1.0.** The DLL exclusion list matched exact filenames;
locally Python 3.14 produced `libcrypto-3.dll` (matched, dropped), while CI's 3.13
produced `libcrypto-3-x64.dll` (didn't match, silently kept). Nothing went red — the
release job was green, the self-check passed, the program ran. An unnecessary DLL doesn't
break anything, it just makes the package fatter. Found by downloading the published
release and measuring it. Matching is now by prefix, and the build **fails** if anything
that should have been stripped is still in the bundle.

## Build & test

```bash
python -m unittest discover          # 181 tests, offscreen, no display needed
python tools/build.py                # -> dist/v-pet/, 65 MB, self-checked
python tools/preview.py docs/states.png
python tools/make_demo.py docs/demo.gif
```

The packaged executable ships a `--selftest` flag that renders every state and reports
via exit code. It exists because ~46 MB of unused Qt DLLs are stripped by filename, and
getting that wrong shows up as "double-click does nothing" — a `console=False` window
application has nowhere to display an exception, so an exit code is the only channel left.

## Compatibility

Click-through, window ledges and desktop icons use Win32 and only work on Windows; other
platforms skip those paths cleanly. Everything else is plain Qt.

## License

MIT — see [LICENSE](LICENSE).

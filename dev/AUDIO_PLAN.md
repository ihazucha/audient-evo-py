# Audio Configuration Improvement Plan

Changes to fix and improve the EVO4 PipeWire/WirePlumber setup.

## 1. Current Issues

### 1.1 WirePlumber Lua config is dead code (HIGH)

`~/.config/wireplumber/main.lua.d/51-evo4-config.lua` uses the WP 0.4 Lua
API (`alsa_monitor.rules`, `table.insert`). WirePlumber 0.5+ ignores Lua
configs entirely — these rules are **silently not applied**:

- Force 2-channel audio position on EVO4 nodes
- Set pro-audio profile
- Disable pause-on-idle

**Fix:** Migrate to `~/.config/wireplumber/wireplumber.conf.d/51-evo4.conf`
using SPA-JSON format (same format as the working `alsa-soft-mixer.conf`):

```
monitor.alsa.rules = [
  {
    matches = [
      { node.name = "~alsa_*.usb-Audient_EVO4-00.*" }
    ]
    actions = {
      update-props = {
        node.pause-on-idle = false
      }
    }
  }
]
```

Then delete `51-evo4-config.lua`.

### 1.2 Systemd service has wrong path (MEDIUM)

`~/.config/systemd/user/evo4-setup.service` references:
```
ExecStart=/home/sasha/.local/bin/evo4-setup.sh
```

Should be `/home/insert/.local/bin/evo4-setup.sh`.

**Fix:** Update the path. Also evaluate whether this service is still
needed — if WirePlumber config handles profile and defaults, the script
becomes redundant.

### 1.3 Unused virtual null sink (LOW)

`evo4-stereo.conf` creates an `evo4-virtual-stereo` null sink
(`support.null-audio-sink`, Audio/Duplex). This node appears in
`pactl list sinks` but nothing routes to it.

**Fix:** Remove the `context.objects` block from `evo4-stereo.conf`.

### 1.4 Broken ALSA profile set reference (LOW)

`evo4-alsa-profiles.conf` sets `device.profile-set = "evo4-stereo.conf"`.
No such profile set file exists in
`/usr/share/alsa-card-profile/mixer/profile-sets/`. ALSA silently falls
back to the default profile set.

**Fix:** Remove `device.profile-set` from the config. The loopback modules
handle stereo remapping regardless of profile set.

### 1.5 Default sink points to disconnected Bluetooth (LOW)

`wpctl status` shows default sink is `bluez_output.94_DB_56_03_22_98.1`
(a Bluetooth device that's currently disconnected).

**Fix:** Set EVO4 stereo output as the configured default:
```bash
wpctl set-default $(wpctl status | grep evo4_stereo_output | awk '{print $1}')
```

## 2. Architecture: Loopback vs Pro-Audio

Two approaches for handling the EVO4's 4ch→2ch mapping:

| | Loopback (current) | Pro-audio profile |
|---|---|---|
| **How** | Virtual 2ch sink/source, forwards to 4ch ALSA | Exposes raw ports (AUX0-3), WP links AUX0+1 |
| **Latency** | +1 quantum (~5ms at 256/48000) | Direct, no extra hop |
| **App compat** | Apps see clean "EVO4 Stereo Output" | Apps see "AUX0, AUX1" (confusing) |
| **pavucontrol** | Clean stereo device | Raw ports, less intuitive |
| **DAW use** | Hides channels 3-4 | Full access to all channels |

**Recommendation:** Keep loopback for desktop use. It's more compatible
and the extra latency is imperceptible. Document pro-audio as an
alternative for DAW workflows where direct channel access matters.

## 3. Config Consolidation

Current state: **6 config files** across 4 directories, some broken.

Target state: **3 files**, all working:

```
~/.config/pipewire/pipewire.conf.d/
  └── evo4-stereo.conf          # Loopback modules only (remove null sink)

~/.config/wireplumber/wireplumber.conf.d/
  ├── alsa-soft-mixer.conf      # Keep as-is (software volume)
  └── 51-evo4.conf              # NEW: device rules + defaults (migrated from Lua)

Remove:
  ~/.config/pipewire/pipewire.conf.d/evo4-alsa-profiles.conf  (broken profile ref)
  ~/.config/pipewire/pipewire-pulse.conf.d/evo4-defaults.conf (move to WP config)
  ~/.config/wireplumber/main.lua.d/51-evo4-config.lua         (dead Lua)

Evaluate:
  ~/.config/systemd/user/evo4-setup.service  (may be redundant after WP migration)
  ~/.local/bin/evo4-setup.sh                 (may be redundant after WP migration)
```

## 4. Future: evoctl ↔ WirePlumber Integration

Ideas for tighter integration between evoctl (hardware controls) and the
PipeWire stack:

- **WP event script**: on EVO4 connect, automatically set hardware volume
  to a sane default via evoctl
- **Volume sync**: map PipeWire volume changes to evoctl hardware volume
  (keep full bit depth by using hardware volume instead of software)
- **Status in waybar**: show current hardware volume/gain in the status bar
  by polling `evoctl.py status`
- **D-Bus service**: expose evoctl as a D-Bus service for desktop
  integration (volume OSD, media keys)

These are non-trivial and should be explored after the config cleanup.

## 5. Action Items

| # | Task | Priority | Effort |
|---|------|----------|--------|
| 1 | Migrate WP Lua config → `.conf` format | High | 15 min |
| 2 | Fix systemd service path | Medium | 1 min |
| 3 | Remove unused null sink from `evo4-stereo.conf` | Low | 1 min |
| 4 | Remove broken ALSA profile set reference | Low | 1 min |
| 5 | Remove `evo4-defaults.conf`, move defaults to WP | Low | 5 min |
| 6 | Delete dead Lua config file | Low | 1 min |
| 7 | Set EVO4 as default sink | Low | 1 min |
| 8 | Test pro-audio profile, document findings | Optional | 30 min |
| 9 | Explore evoctl + WirePlumber integration | Future | hours |

Items 1-7 can be done in one session. Item 8 is experimental. Item 9 is
a separate project.

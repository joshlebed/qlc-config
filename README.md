# QLC+ Lighting System Configuration

Configuration and documentation for the QLC+ lighting control system on the media server.

## Architecture Overview

```
┌─────────────────┐     OSC (UDP 7700)     ┌─────────────┐
│  Home Assistant │ ──────────────────────▶│   QLC+      │
│  or Python      │                        │  (headless) │
└─────────────────┘                        └──────┬──────┘
                                                  │ DMX512
                                                  ▼
                                           ┌─────────────┐
                                           │  USB-DMX    │
                                           │  Interface  │
                                           └──────┬──────┘
                                                  │
                                           ┌──────▼──────┐
                                           │  Fixtures   │
                                           └─────────────┘
```

## Hardware

### USB-DMX Interface
- **Type**: FTDI FT232R USB UART (ProX or similar)
- **Vendor ID**: 0403
- **Product ID**: 6001
- **Serial**: A402PX50
- **Device**: `/dev/ttyUSB0`

### Fixtures
<!-- Document your fixtures here -->
- TBD: Add fixture details after GUI configuration

## Server Setup (Fresh Install)

### 1. Install packages

```bash
sudo apt update
sudo apt install -y qlcplus xvfb python3-pip
pip3 install python-osc --break-system-packages
```

### 2. Add user to dialout group (for USB-DMX access)

```bash
sudo usermod -a -G dialout $USER
# Log out and back in, or reboot
```

### 3. Create directory structure

```bash
sudo mkdir -p /opt/qlcplus/projects
sudo chown -R $USER:$USER /opt/qlcplus
```

### 4. Install systemd service

```bash
sudo cp /home/joshlebed/code/qlc-config/qlcplus.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable qlcplus
```

### 5. Symlink project file

The QLC+ project file lives in this repo and is symlinked to where QLC+ expects it:

```bash
ln -sf /home/joshlebed/code/qlc-config/spotlight.qxw /opt/qlcplus/projects/spotlight.qxw
```

This way, changes saved in QLC+ are automatically in the repo—no copying needed.

### 6. Start service

```bash
sudo systemctl start qlcplus
journalctl -u qlcplus -f  # verify it's running
```

## File Locations

| File | Location | Purpose |
|------|----------|---------|
| QLC+ project (actual) | `/home/joshlebed/code/qlc-config/spotlight.qxw` | Version-controlled project file |
| QLC+ project (symlink) | `/opt/qlcplus/projects/spotlight.qxw` | Symlink to repo file |
| Systemd service (actual) | `/home/joshlebed/code/qlc-config/qlcplus.service` | Version-controlled service file |
| Systemd service (installed) | `/etc/systemd/system/qlcplus.service` | Installed copy |
| OSC control script | `/home/joshlebed/code/qlc-config/osc_control.py` | Python CLI for OSC commands |

## OSC Control

QLC+ listens for OSC on **UDP port 7700** by default.

### Command Line Usage

```bash
# Use the control script
python3 /opt/qlcplus/osc_control.py off
python3 /opt/qlcplus/osc_control.py audio
python3 /opt/qlcplus/osc_control.py solid
python3 /opt/qlcplus/osc_control.py manual

# Or send custom OSC addresses
python3 /opt/qlcplus/osc_control.py /custom/address 0.5
```

### Python Integration

```python
from pythonosc import udp_client

client = udp_client.SimpleUDPClient("127.0.0.1", 7700)
client.send_message("/lights/mode/off", 1)
client.send_message("/lights/mode/audio", 1)
```

### OSC Address Conventions

| Address | Function |
|---------|----------|
| `/lights/mode/off` | All lights off |
| `/lights/mode/audio` | Audio-reactive mode |
| `/lights/mode/solid` | Static color mode |
| `/lights/mode/manual` | Manual DMX control |

## GUI Configuration (One-Time Setup)

QLC+ requires a GUI session to create/edit the lighting project. After initial setup, it runs headless.

### Option A: X11 Forwarding from macOS (Recommended)

#### On the Mac (one-time setup):

1. Install XQuartz:
   ```bash
   brew install --cask xquartz
   ```
   Or download from https://www.xquartz.org/

2. Log out and back in (or reboot) after installing

3. Launch XQuartz from Applications

4. Configure XQuartz:
   - **XQuartz → Settings → Security**
   - Check: **"Allow connections from network clients"**

5. Add to `~/.ssh/config` on your Mac:
   ```
   Host mediaserver
       HostName <server-ip-or-hostname>
       User joshlebed
       ForwardX11 yes
       ForwardX11Trusted yes
   ```

#### Connect and run:

```bash
ssh mediaserver   # or: ssh -Y joshlebed@<server-ip>
qlcplus
```

**Important:** You must start a fresh SSH session with X11 forwarding. Existing terminal sessions (e.g., where you're running other tools) won't have `DISPLAY` set and QLC+ will fail with "could not connect to display".

#### Verify X11 is working:
```bash
echo $DISPLAY     # Should show "localhost:10.0" or similar
xeyes             # Should open a window with eyes on your Mac
```

#### Troubleshooting X11:
- If `DISPLAY` is empty, you didn't SSH with `-X` or `-Y`, or XQuartz isn't running
- If you get "Authorization required", enable "Allow connections from network clients" in XQuartz settings
- If it's slow, use `-Y` (trusted) instead of `-X`, or add `-C` for compression

### Option B: Direct Display

Plug in a monitor and keyboard to the server temporarily.

### Option C: VNC/NoMachine

Use remote desktop software.

### What to Configure in GUI

1. **Add Fixtures**
   - Match DMX mode exactly to your hardware
   - Set starting DMX address (typically 1)

2. **Create Functions**
   - `mode_off` - Scene with all channels at 0
   - `mode_audio` - Audio trigger configuration
   - `mode_solid` - Static color scene
   - `mode_manual` - Collection for manual control

3. **Virtual Console**
   - Create buttons for each mode
   - Set buttons to Toggle, Exclusive Group
   - Bind OSC addresses to each button

4. **Audio Setup**
   - Select audio input device
   - Configure audio trigger spectrum bands
   - Map to fixture channels

5. **Save Project**
   - Save to `/opt/qlcplus/projects/spotlight.qxw`
   - This is a symlink to the repo, so changes are automatically version-controlled
   - Just `git commit` after saving

## Service Management

```bash
# Start/stop/restart
sudo systemctl start qlcplus
sudo systemctl stop qlcplus
sudo systemctl restart qlcplus

# Check status
sudo systemctl status qlcplus

# View logs
journalctl -u qlcplus -f

# Enable/disable on boot
sudo systemctl enable qlcplus
sudo systemctl disable qlcplus
```

## Troubleshooting

### QLC+ won't start

Check if xvfb is working:
```bash
xvfb-run qlcplus --version
```

### No DMX output

1. Verify USB device is present:
   ```bash
   ls /dev/ttyUSB*
   ```

2. Check user is in dialout group:
   ```bash
   groups | grep dialout
   ```

3. Check QLC+ output patch (requires GUI)

### OSC commands not working

1. Verify QLC+ is running:
   ```bash
   sudo systemctl status qlcplus
   ```

2. Check OSC is enabled in QLC+ input/output configuration

3. Test with netcat:
   ```bash
   echo -n "/lights/mode/off" | nc -u 127.0.0.1 7700
   ```

### USB device not detected after reboot

Create a udev rule for consistent naming:
```bash
sudo tee /etc/udev/rules.d/99-usb-dmx.rules << 'EOF'
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", SYMLINK+="dmx0"
EOF
sudo udevadm control --reload-rules
```

## Backup and Version Control

The project file is symlinked from the repo, so no copying is needed.

### After modifying the project in QLC+ GUI:

```bash
cd /home/joshlebed/code/qlc-config
git add spotlight.qxw
git commit -m "Update lighting project"
git push
```

### Restoring from git history:

```bash
cd /home/joshlebed/code/qlc-config
git checkout <commit-hash> -- spotlight.qxw
sudo systemctl restart qlcplus
```

### Setting up on a new machine:

```bash
# Clone the repo
git clone <repo-url> /home/joshlebed/code/qlc-config

# Follow "Server Setup (Fresh Install)" steps 1-4, then:
ln -sf /home/joshlebed/code/qlc-config/spotlight.qxw /opt/qlcplus/projects/spotlight.qxw

# Start service
sudo systemctl start qlcplus
```

## TODO

- [ ] Complete GUI configuration session
- [ ] Document actual fixtures and DMX addresses
- [ ] Configure audio input
- [ ] Test OSC integration
- [ ] Set up Home Assistant integration (optional)

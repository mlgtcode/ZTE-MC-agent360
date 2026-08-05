# ZTEROUTER MC AGENT360 Plugin

This is a custom AGENT360 / 360 Monitoring ([360monitoring.com](https://360monitoring.com)) plugin for collecting telemetry from ZTE routers (MC and related models) through the local router API.

## Features

- Local router polling over HTTP/HTTPS
- Authentication flow compatible with MC-series routers
- Grouped telemetry output:
  - system_info
  - radio_network
  - connectivity
  - ipv6_config
  - wifi
  - wifi_advanced
  - power_sensors
  - usage_misc
  - dns_config
  - unclassified
- Automatic add_params group for extra router keys not predefined

## Requirements

- AGENT360 agent installed
- Python environment used by AGENT360 with:
  - urllib3
- Network access from agent host to router web interface

## Installation

1. Copy the plugin file to your AGENT360 plugins directory as `ZTEROUTER.py`.
2. Edit `/etc/agent360-custom.ini` and add:

```ini
[ZTEROUTER]
enabled = yes
ip = 192.168.1.1
password = your_router_password
# username is optional; some ZTE routers do not require it.
# username = admin
```

3. Test plugin output:

```bash
agent360 test ZTEROUTER
```

4. Restart agent:

```bash
service agent360 restart
```

## Configuration

Section name must match plugin name exactly: `ZTEROUTER`.

Supported keys:

- `enabled`: yes or no
- `ip`: router IP address
- `password`: router password
- `username`: optional for routers requiring multi-user login

## Credits

Special thanks to Kajkac and contributors of the ZTE Home Assistant integration.

Base source inspiration:  
https://github.com/Kajkac/ZTE-MC-Home-assistant-repo/blob/main/custom_components/zte_router/mc.py

Upstream project:  
https://github.com/Kajkac/ZTE-MC-Home-assistant-repo

License note:  
Upstream repository is GPL-3.0. Review licensing obligations before redistribution or packaging.

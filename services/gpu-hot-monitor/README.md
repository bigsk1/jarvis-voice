# GPU Hot Monitor

Monitors the private GPU Hot dashboard host and sends sustained threshold failures to the existing Jarvis alerts API. High alerts are spoken through the normal Jarvis alert/TTS path; no email or n8n workflow is involved.

The monitor opens GPU Hot's WebSocket long enough to read one snapshot, closes it, then waits for the next poll. That snapshot includes GPU metrics, active GPU processes, and host CPU/RAM/load data. If the WebSocket is unavailable, it falls back to the GPU-only REST endpoint.

## GPU Hot container on the monitored host

The `--pid=host` option is required for GPU Hot to report GPU processes running outside its container. To update or recreate the container:

```bash
docker pull ghcr.io/psalias2006/gpu-hot:latest
docker rm -f gpu-hot
docker run -d --name gpu-hot --restart unless-stopped --init --pid=host --gpus all -p 1312:1312 ghcr.io/psalias2006/gpu-hot:latest
```

Check it afterward:

```bash
curl http://GPU_HOST:1312/api/version
curl http://GPU_HOST:1312/api/gpu-data | jq .
```

GPU Hot has no authentication layer, so expose port 1312 only on the trusted LAN or behind an authenticated reverse proxy.

## Configure

The real `config.env` is Git-ignored because it contains the private host URL and may contain the Jarvis API key.

```bash
cd ~/jarvis-voice/services/gpu-hot-monitor
cp config.env.example config.env
nano config.env
```

Temperature monitoring starts with a conservative sustained threshold: 80 C for four consecutive 30-second samples, recovering after two samples at or below 75 C. Endpoint failure alerts after three consecutive failed checks.

Allocated VRAM capacity and GPU utilization are independently tunable and disabled by default:

```dotenv
# Alert when allocated VRAM remains at or above 95% for four samples.
GPU_HOT_VRAM_PERCENT=95
GPU_HOT_VRAM_RECOVERY_PERCENT=90
GPU_HOT_VRAM_SAMPLES=4

# Alert when compute utilization remains at or above 98% for ten samples.
GPU_HOT_UTILIZATION_PERCENT=98
GPU_HOT_UTILIZATION_RECOVERY_PERCENT=90
GPU_HOT_UTILIZATION_SAMPLES=10
```

GPU Hot calls its memory-controller activity field `memory_utilization`; Jarvis deliberately does not use that as allocated capacity. VRAM capacity is calculated as `memory_used / memory_total * 100`.

Host CPU and RAM thresholds are also available but disabled by default. Current host information is always returned by the `gpu_hot_status` tool when the WebSocket snapshot succeeds.

## Validate without creating an alert

```bash
cd ~/jarvis-voice/services/gpu-hot-monitor
set -a
source config.env
set +a
~/jarvis-venv/bin/python3 gpu_hot_monitor.py --once --dry-run
```

## Install the service

```bash
cd ~/jarvis-voice/services/gpu-hot-monitor
../../bin/render-systemd-unit.sh gpu-hot-monitor.service /tmp/gpu-hot-monitor.service
sudo cp /tmp/gpu-hot-monitor.service /etc/systemd/system/gpu-hot-monitor.service
sudo systemctl daemon-reload
sudo systemctl enable --now gpu-hot-monitor
```

Service management:

```bash
sudo systemctl status gpu-hot-monitor
sudo journalctl -u gpu-hot-monitor -f
sudo systemctl restart gpu-hot-monitor
sudo systemctl stop gpu-hot-monitor
```

The service persists only alert state in `logs/gpu-hot-monitor-state.json`. A stable dedupe key prevents duplicate pending alerts, and the monitor resolves its alert after the configured number of healthy recovery samples.

## On-demand Jarvis tool

The first-class `gpu_hot_status` tool uses `GPU_HOT_URL` when present. Otherwise it reuses this service's ignored `config.env`, which avoids duplicating the private URL. It is separate from `system_monitor`: the latter describes the Jarvis machine, while `gpu_hot_status` describes the remote helper host.

Manual tool check:

```bash
.venv/bin/python skills/gpu_hot_status.py '{}'
```

Upstream project: [psalias2006/gpu-hot](https://github.com/psalias2006/gpu-hot)

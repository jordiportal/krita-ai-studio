# Krita AI Studio

Web application that replicates the [krita-ai-diffusion](https://github.com/Acly/krita-ai-diffusion) plugin's image generation workflow. Connects to an external ComfyUI server and produces identical results using the same nodes, parameters, and styles.

## Features

- **Exact workflow replication** of krita-ai-diffusion (SamplerCustomAdvanced, CFGGuider, ETN_SaveImageCache, etc.)
- **Model-aware defaults** — auto-detects Illustrious, SDXL, Flux, SD3, SD1.5 and applies the correct sampler, scheduler, steps, CFG, style prompt, and negative prompt
- **Mobile-friendly UI** — prompt + strength as primary controls, everything else in collapsible advanced options
- **SQLite persistence** — settings survive container restarts
- **Single Docker container** — Angular frontend + FastAPI backend

## Quick Start

```bash
cp .env.example .env
# Edit .env with your ComfyUI host

docker compose up --build -d
```

The app will be available at `http://localhost:3333`.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `COMFYUI_HOST` | `comfyui.khlloreda.com` | ComfyUI server hostname |
| `COMFYUI_PORT` | `80` | ComfyUI server port |
| `COMFYUI_SECURE` | `false` | Use HTTPS |
| `KRITA_HTTP_PORT` | `3333` | Local port to expose |

## Architecture

```
┌─────────────────────────────────┐
│  Docker Container               │
│  ┌───────────┐ ┌──────────────┐ │
│  │  Angular   │ │   FastAPI    │ │    ┌──────────┐
│  │  Frontend  │→│   Backend    │─┼───→│ ComfyUI  │
│  │  :3000     │ │   + SQLite   │ │    │ (external)│
│  └───────────┘ └──────────────┘ │    └──────────┘
└─────────────────────────────────┘
```

## Requirements

Your ComfyUI server needs these custom nodes installed:
- [comfyui-tooling-nodes](https://github.com/Acly/comfyui-tooling-nodes) (ETN_SaveImageCache)
- Standard ComfyUI nodes: RandomNoise, KSamplerSelect, BasicScheduler, CFGGuider, SamplerCustomAdvanced

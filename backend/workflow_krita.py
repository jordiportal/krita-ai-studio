"""
Workflow generator for Krita AI Studio.

Uses architectures.json (via ArchManager) for model-specific configuration
instead of hardcoded dicts. Supports both checkpoint and diffusion model loaders.

Main entry point: build_txt2img_workflow(arch_config, prompt, ...)
"""

import re
from typing import Dict, Any, List, Tuple, Optional

from architectures import get_arch_manager


def parse_lora_tags(prompt: str) -> Tuple[str, List[Tuple[str, float]]]:
    """
    Extrae tags <lora:nombre:peso> del prompt.
    Retorna (prompt_limpio, [(nombre, peso), ...])
    Soporta variantes: <lora:name:0.8>, <lora:name>, <lora:name:0.8:0.6>
    El tercer valor opcional es strength_clip (si se omite, usa el mismo que model).
    """
    pattern = r"<lora:([^:>]+)(?::([^:>]*))?(?::([^:>]*))?>"""
    loras: List[Tuple[str, float, float]] = []

    for match in re.finditer(pattern, prompt):
        name = match.group(1).strip()
        strength_model = float(match.group(2)) if match.group(2) else 1.0
        strength_clip = float(match.group(3)) if match.group(3) else strength_model
        loras.append((name, strength_model, strength_clip))

    clean_prompt = re.sub(pattern, "", prompt).strip()
    clean_prompt = re.sub(r",\s*,", ",", clean_prompt).strip(", ")

    return clean_prompt, loras


def resolve_lora_filename(lora_name: str, available_loras: List[str]) -> str | None:
    """
    Resuelve un nombre parcial de LoRA al filename real.
    Búsqueda: exacto > sin extensión > substring case-insensitive.
    """
    if not available_loras:
        return None

    for f in available_loras:
        if f == lora_name or f == f"{lora_name}.safetensors":
            return f

    name_lower = lora_name.lower()
    for f in available_loras:
        stem = f.rsplit(".", 1)[0].lower()
        if stem == name_lower:
            return f

    for f in available_loras:
        if name_lower in f.lower():
            return f

    return None


def build_txt2img_workflow(
    arch_config: Dict[str, Any],
    prompt: str,
    negative_prompt: str = "",
    model_name: str = "SDXL.safetensors",
    sampler: str = "",
    scheduler: str = "",
    steps: int = 0,
    cfg: float = 0,
    seed: int = -1,
    width: int = 1024,
    height: int = 1024,
    batch_size: int = 1,
    loras: List[Tuple[str, float, float]] | None = None,
) -> Dict[str, Any]:
    """
    Unified txt2img workflow builder driven by arch_config (from ArchManager.resolve()).

    arch_config fields used:
      loader: "checkpoint" | "diffusion"
      clip: {mode, type, clip1, clip2}
      vae: str | null
      weight_dtype: str (for diffusion loader)
      latent_node: "EmptyLatentImage" | "EmptySD3LatentImage"
      guidance: {type: "cfg"|"flux"|"basic", default: float}
      sampling: {sampler, scheduler, steps, cfg}
      prompt: {style, negative}
      rescale_cfg: bool
    """

    sampling = arch_config.get("sampling", {})
    actual_sampler = sampler if sampler else sampling.get("sampler", "euler")
    actual_scheduler = scheduler if scheduler else sampling.get("scheduler", "normal")
    actual_steps = steps if steps > 0 else sampling.get("steps", 20)
    actual_cfg = cfg if cfg > 0 else sampling.get("cfg", 7.0)

    prompt_cfg = arch_config.get("prompt", {})
    style = prompt_cfg.get("style", "{prompt}")
    final_prompt = style.replace("{prompt}", prompt)
    final_negative = negative_prompt if negative_prompt else prompt_cfg.get("negative", "")

    guidance = arch_config.get("guidance", {})
    guidance_type = guidance.get("type", "cfg")

    loader_type = arch_config.get("loader", "checkpoint")
    clip_cfg = arch_config.get("clip", {})
    latent_node = arch_config.get("latent_node", "EmptyLatentImage")

    workflow: Dict[str, Any] = {}
    node_id = 1

    # ── Model loading ──
    if loader_type == "diffusion":
        unet_id = str(node_id)
        workflow[unet_id] = {
            "_meta": {"title": "UNET Model"},
            "inputs": {
                "unet_name": model_name,
                "weight_dtype": arch_config.get("weight_dtype", "default"),
            },
            "class_type": "UNETLoader",
        }
        model_ref = [unet_id, 0]
        node_id += 1

        clip_mode = clip_cfg.get("mode", "dual")
        clip_loader_id = str(node_id)
        if clip_mode == "single":
            workflow[clip_loader_id] = {
                "_meta": {"title": "CLIP Loader"},
                "inputs": {
                    "clip_name": clip_cfg.get("clip1", ""),
                    "type": clip_cfg.get("type", "flux"),
                },
                "class_type": "CLIPLoader",
            }
        else:
            workflow[clip_loader_id] = {
                "_meta": {"title": "CLIP Loader"},
                "inputs": {
                    "clip_name1": clip_cfg.get("clip1", ""),
                    "clip_name2": clip_cfg.get("clip2", clip_cfg.get("clip1", "")),
                    "type": clip_cfg.get("type", "flux"),
                },
                "class_type": "DualCLIPLoader",
            }
        clip_ref = [clip_loader_id, 0]
        node_id += 1

        vae_name = arch_config.get("vae")
        vae_loader_id = str(node_id)
        workflow[vae_loader_id] = {
            "_meta": {"title": "VAE Loader"},
            "inputs": {"vae_name": vae_name or "ae.safetensors"},
            "class_type": "VAELoader",
        }
        vae_ref = [vae_loader_id, 0]
        node_id += 1

    else:
        checkpoint_id = str(node_id)
        workflow[checkpoint_id] = {
            "_meta": {"title": "Checkpoint"},
            "inputs": {"ckpt_name": model_name},
            "class_type": "CheckpointLoaderSimple",
        }
        model_ref = [checkpoint_id, 0]
        clip_ref = [checkpoint_id, 1]
        vae_ref = [checkpoint_id, 2]
        node_id += 1

    # ── LoRA Loaders ──
    if loras:
        for lora_filename, strength_model, strength_clip in loras:
            lora_id = str(node_id)
            workflow[lora_id] = {
                "_meta": {"title": f"LoRA: {lora_filename}"},
                "inputs": {
                    "lora_name": lora_filename,
                    "strength_model": strength_model,
                    "strength_clip": strength_clip,
                    "model": model_ref,
                    "clip": clip_ref,
                },
                "class_type": "LoraLoader",
            }
            model_ref = [lora_id, 0]
            clip_ref = [lora_id, 1]
            node_id += 1

    # ── Positive prompt ──
    positive_id = str(node_id)
    workflow[positive_id] = {
        "_meta": {"title": "Positive Prompt"},
        "inputs": {"text": final_prompt, "clip": clip_ref},
        "class_type": "CLIPTextEncode",
    }
    positive_ref = [positive_id, 0]
    node_id += 1

    # ── Negative / ConditioningZeroOut ──
    if guidance_type in ("flux", "basic"):
        negative_id = str(node_id)
        workflow[negative_id] = {
            "_meta": {"title": "Zero Conditioning"},
            "inputs": {"conditioning": positive_ref},
            "class_type": "ConditioningZeroOut",
        }
        negative_ref = [negative_id, 0]
        node_id += 1
    elif final_negative and final_negative.strip():
        negative_id = str(node_id)
        workflow[negative_id] = {
            "_meta": {"title": "Negative Prompt"},
            "inputs": {"text": final_negative, "clip": clip_ref},
            "class_type": "CLIPTextEncode",
        }
        negative_ref = [negative_id, 0]
        node_id += 1
    else:
        negative_id = str(node_id)
        workflow[negative_id] = {
            "_meta": {"title": "Zero Conditioning"},
            "inputs": {"conditioning": positive_ref},
            "class_type": "ConditioningZeroOut",
        }
        negative_ref = [negative_id, 0]
        node_id += 1

    # ── Empty latent ──
    latent_id = str(node_id)
    workflow[latent_id] = {
        "_meta": {"title": "Empty Latent"},
        "inputs": {"width": width, "height": height, "batch_size": batch_size},
        "class_type": latent_node,
    }
    latent_ref = [latent_id, 0]
    node_id += 1

    # ── RandomNoise ──
    noise_id = str(node_id)
    workflow[noise_id] = {
        "_meta": {"title": "Random Noise"},
        "inputs": {"noise_seed": seed},
        "class_type": "RandomNoise",
    }
    noise_ref = [noise_id, 0]
    node_id += 1

    # ── KSamplerSelect ──
    sampler_select_id = str(node_id)
    workflow[sampler_select_id] = {
        "_meta": {"title": "Sampler"},
        "inputs": {"sampler_name": actual_sampler},
        "class_type": "KSamplerSelect",
    }
    sampler_ref = [sampler_select_id, 0]
    node_id += 1

    # ── BasicScheduler ──
    scheduler_id = str(node_id)
    workflow[scheduler_id] = {
        "_meta": {"title": "Scheduler"},
        "inputs": {
            "model": model_ref,
            "scheduler": actual_scheduler,
            "steps": actual_steps,
            "denoise": 1.0,
        },
        "class_type": "BasicScheduler",
    }
    sigmas_ref = [scheduler_id, 0]
    node_id += 1

    # ── Guider ──
    if guidance_type == "flux":
        default_guidance = guidance.get("default", 3.5)
        flux_guid_id = str(node_id)
        workflow[flux_guid_id] = {
            "_meta": {"title": "Flux Guidance"},
            "inputs": {
                "conditioning": positive_ref,
                "guidance": default_guidance if actual_cfg <= 1 else actual_cfg,
            },
            "class_type": "FluxGuidance",
        }
        guider_cond_ref = [flux_guid_id, 0]
        node_id += 1

        guider_id = str(node_id)
        workflow[guider_id] = {
            "_meta": {"title": "Guider"},
            "inputs": {"model": model_ref, "conditioning": guider_cond_ref},
            "class_type": "BasicGuider",
        }
    elif guidance_type == "basic":
        guider_id = str(node_id)
        workflow[guider_id] = {
            "_meta": {"title": "Guider"},
            "inputs": {"model": model_ref, "conditioning": positive_ref},
            "class_type": "BasicGuider",
        }
    elif actual_cfg == 1.0:
        guider_id = str(node_id)
        workflow[guider_id] = {
            "_meta": {"title": "Guider"},
            "inputs": {"model": model_ref, "conditioning": positive_ref},
            "class_type": "BasicGuider",
        }
    else:
        guider_id = str(node_id)
        workflow[guider_id] = {
            "_meta": {"title": "CFG Guider"},
            "inputs": {
                "model": model_ref,
                "positive": positive_ref,
                "negative": negative_ref,
                "cfg": actual_cfg,
            },
            "class_type": "CFGGuider",
        }
    guider_ref = [guider_id, 0]
    node_id += 1

    # ── SamplerCustomAdvanced ──
    sampler_adv_id = str(node_id)
    workflow[sampler_adv_id] = {
        "_meta": {"title": "Sampler Advanced"},
        "inputs": {
            "noise": noise_ref,
            "guider": guider_ref,
            "sampler": sampler_ref,
            "sigmas": sigmas_ref,
            "latent_image": latent_ref,
        },
        "class_type": "SamplerCustomAdvanced",
    }
    sampler_output_ref = [sampler_adv_id, 1]
    node_id += 1

    # ── VAEDecode ──
    decode_id = str(node_id)
    workflow[decode_id] = {
        "_meta": {"title": "VAE Decode"},
        "inputs": {"samples": sampler_output_ref, "vae": vae_ref},
        "class_type": "VAEDecode",
    }
    image_ref = [decode_id, 0]
    node_id += 1

    # ── ETN_SaveImageCache ──
    cache_id = str(node_id)
    workflow[cache_id] = {
        "_meta": {"title": "Save to Cache"},
        "inputs": {"images": image_ref, "format": "PNG"},
        "class_type": "ETN_SaveImageCache",
    }

    return workflow


def build_txt2video_workflow(
    arch_config: Dict[str, Any],
    prompt: str,
    negative_prompt: str = "",
    model_name: str = "wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors",
    low_noise_model: Optional[str] = None,
    vae_override: str = "",
    clip_override: str = "",
    sampler: str = "",
    scheduler: str = "",
    steps: int = 0,
    cfg: float = 0,
    seed: int = -1,
    width: int = 832,
    height: int = 480,
    length: int = 81,
    fps: float = 8.0,
    batch_size: int = 1,
    loras: List[Tuple[str, float, float]] | None = None,
) -> Dict[str, Any]:
    """
    Wan 2.x T2V alineado con el blueprint oficial de ComfyUI:
    - ModelSamplingSD3 (flow matching, shift ~5)
    - Dos fases high_noise + low_noise cuando existe el UNet low en disco
    - SplitSigmas + segunda pasada con DisableNoise (sin reinyectar ruido)
    - WEBP sin pérdida por defecto (menos bandas de color)
    """
    sampling = arch_config.get("sampling", {})
    actual_sampler = sampler if sampler else sampling.get("sampler", "euler")
    actual_scheduler = scheduler if scheduler else sampling.get("scheduler", "simple")
    actual_steps = steps if steps > 0 else sampling.get("steps", 20)
    actual_cfg = cfg if cfg > 0 else float(sampling.get("cfg", 1.0))

    shift = float(arch_config.get("model_sampling_shift", 5.0))
    webp_lossless = bool(arch_config.get("video_webp_lossless", True))

    dual_stage = (
        low_noise_model is not None
        and low_noise_model != model_name
        and actual_steps >= 2
    )
    split_step = max(1, min(actual_steps - 1, actual_steps // 2))

    clip_cfg = arch_config.get("clip", {})
    clip_name = clip_override or clip_cfg.get("clip1", "umt5_xxl_fp8_e4m3fn_scaled.safetensors")
    vae_name = vae_override or arch_config.get("vae", "wan_2.1_vae.safetensors")

    workflow: Dict[str, Any] = {}
    node_id = 1

    # ── 1. UNETLoader (high / único) ──
    unet_high_id = str(node_id)
    workflow[unet_high_id] = {
        "_meta": {"title": "Wan UNET (high)"},
        "inputs": {
            "unet_name": model_name,
            "weight_dtype": arch_config.get("weight_dtype", "default"),
        },
        "class_type": "UNETLoader",
    }
    model_ref = [unet_high_id, 0]
    node_id += 1

    # ── 2. CLIPLoader ──
    clip_id = str(node_id)
    workflow[clip_id] = {
        "_meta": {"title": "Wan CLIP"},
        "inputs": {
            "clip_name": clip_name,
            "type": clip_cfg.get("type", "wan"),
        },
        "class_type": "CLIPLoader",
    }
    clip_ref = [clip_id, 0]
    node_id += 1

    # ── 3. VAELoader ──
    vae_id = str(node_id)
    workflow[vae_id] = {
        "_meta": {"title": "Wan VAE"},
        "inputs": {"vae_name": vae_name},
        "class_type": "VAELoader",
    }
    vae_ref = [vae_id, 0]
    node_id += 1

    # ── LoRA Loaders (modelo high + clip) ──
    if loras:
        for lora_filename, strength_model, strength_clip in loras:
            lora_id = str(node_id)
            workflow[lora_id] = {
                "_meta": {"title": f"LoRA: {lora_filename}"},
                "inputs": {
                    "lora_name": lora_filename,
                    "strength_model": strength_model,
                    "strength_clip": strength_clip,
                    "model": model_ref,
                    "clip": clip_ref,
                },
                "class_type": "LoraLoader",
            }
            model_ref = [lora_id, 0]
            clip_ref = [lora_id, 1]
            node_id += 1

    # ── ModelSamplingSD3 sobre UNet high (después de LoRAs) ──
    ms_high_id = str(node_id)
    workflow[ms_high_id] = {
        "_meta": {"title": "ModelSamplingSD3 (high)"},
        "inputs": {"model": model_ref, "shift": shift},
        "class_type": "ModelSamplingSD3",
    }
    model_high_samp = [ms_high_id, 0]
    node_id += 1

    if dual_stage:
        unet_low_id = str(node_id)
        workflow[unet_low_id] = {
            "_meta": {"title": "Wan UNET (low)"},
            "inputs": {
                "unet_name": low_noise_model,
                "weight_dtype": arch_config.get("weight_dtype", "default"),
            },
            "class_type": "UNETLoader",
        }
        model_low_raw = [unet_low_id, 0]
        node_id += 1

        ms_low_id = str(node_id)
        workflow[ms_low_id] = {
            "_meta": {"title": "ModelSamplingSD3 (low)"},
            "inputs": {"model": model_low_raw, "shift": shift},
            "class_type": "ModelSamplingSD3",
        }
        model_low_samp = [ms_low_id, 0]
        node_id += 1

    # ── CLIPTextEncode ──
    positive_id = str(node_id)
    workflow[positive_id] = {
        "_meta": {"title": "Positive Prompt"},
        "inputs": {"text": prompt, "clip": clip_ref},
        "class_type": "CLIPTextEncode",
    }
    positive_ref = [positive_id, 0]
    node_id += 1

    negative_id = str(node_id)
    workflow[negative_id] = {
        "_meta": {"title": "Negative Prompt"},
        "inputs": {
            "text": negative_prompt if negative_prompt else "",
            "clip": clip_ref,
        },
        "class_type": "CLIPTextEncode",
    }
    negative_ref = [negative_id, 0]
    node_id += 1

    # ── WanImageToVideo ──
    wan_latent_id = str(node_id)
    workflow[wan_latent_id] = {
        "_meta": {"title": "Wan T2V Latent"},
        "inputs": {
            "positive": positive_ref,
            "negative": negative_ref,
            "vae": vae_ref,
            "width": width,
            "height": height,
            "length": length,
            "batch_size": batch_size,
        },
        "class_type": "WanImageToVideo",
    }
    latent_ref = [wan_latent_id, 2]
    positive_cond_ref = [wan_latent_id, 0]
    negative_cond_ref = [wan_latent_id, 1]
    node_id += 1

    # ── RandomNoise + KSamplerSelect ──
    noise_id = str(node_id)
    workflow[noise_id] = {
        "_meta": {"title": "Random Noise"},
        "inputs": {"noise_seed": seed},
        "class_type": "RandomNoise",
    }
    noise_ref = [noise_id, 0]
    node_id += 1

    sampler_select_id = str(node_id)
    workflow[sampler_select_id] = {
        "_meta": {"title": "Sampler"},
        "inputs": {"sampler_name": actual_sampler},
        "class_type": "KSamplerSelect",
    }
    sampler_ref = [sampler_select_id, 0]
    node_id += 1

    if dual_stage:
        sched_id = str(node_id)
        workflow[sched_id] = {
            "_meta": {"title": "Scheduler"},
            "inputs": {
                "model": model_high_samp,
                "scheduler": actual_scheduler,
                "steps": actual_steps,
                "denoise": 1.0,
            },
            "class_type": "BasicScheduler",
        }
        sigmas_full_ref = [sched_id, 0]
        node_id += 1

        split_id = str(node_id)
        workflow[split_id] = {
            "_meta": {"title": "SplitSigmas"},
            "inputs": {"sigmas": sigmas_full_ref, "step": split_step},
            "class_type": "SplitSigmas",
        }
        sigmas_high_ref = [split_id, 0]
        sigmas_low_ref = [split_id, 1]
        node_id += 1

        guider_h_id = str(node_id)
        workflow[guider_h_id] = {
            "_meta": {"title": "CFG Guider (high)"},
            "inputs": {
                "model": model_high_samp,
                "positive": positive_cond_ref,
                "negative": negative_cond_ref,
                "cfg": actual_cfg,
            },
            "class_type": "CFGGuider",
        }
        guider_high_ref = [guider_h_id, 0]
        node_id += 1

        samp1_id = str(node_id)
        workflow[samp1_id] = {
            "_meta": {"title": "Sampler stage 1 (high noise)"},
            "inputs": {
                "noise": noise_ref,
                "guider": guider_high_ref,
                "sampler": sampler_ref,
                "sigmas": sigmas_high_ref,
                "latent_image": latent_ref,
            },
            "class_type": "SamplerCustomAdvanced",
        }
        latent_after_high = [samp1_id, 0]
        node_id += 1

        disable_noise_id = str(node_id)
        workflow[disable_noise_id] = {
            "_meta": {"title": "DisableNoise"},
            "inputs": {},
            "class_type": "DisableNoise",
        }
        empty_noise_ref = [disable_noise_id, 0]
        node_id += 1

        guider_l_id = str(node_id)
        workflow[guider_l_id] = {
            "_meta": {"title": "CFG Guider (low)"},
            "inputs": {
                "model": model_low_samp,
                "positive": positive_cond_ref,
                "negative": negative_cond_ref,
                "cfg": actual_cfg,
            },
            "class_type": "CFGGuider",
        }
        guider_low_ref = [guider_l_id, 0]
        node_id += 1

        samp2_id = str(node_id)
        workflow[samp2_id] = {
            "_meta": {"title": "Sampler stage 2 (low noise)"},
            "inputs": {
                "noise": empty_noise_ref,
                "guider": guider_low_ref,
                "sampler": sampler_ref,
                "sigmas": sigmas_low_ref,
                "latent_image": latent_after_high,
            },
            "class_type": "SamplerCustomAdvanced",
        }
        sampler_output_ref = [samp2_id, 0]
        node_id += 1
    else:
        sched_id = str(node_id)
        workflow[sched_id] = {
            "_meta": {"title": "Scheduler"},
            "inputs": {
                "model": model_high_samp,
                "scheduler": actual_scheduler,
                "steps": actual_steps,
                "denoise": 1.0,
            },
            "class_type": "BasicScheduler",
        }
        sigmas_ref = [sched_id, 0]
        node_id += 1

        guider_id = str(node_id)
        workflow[guider_id] = {
            "_meta": {"title": "CFG Guider"},
            "inputs": {
                "model": model_high_samp,
                "positive": positive_cond_ref,
                "negative": negative_cond_ref,
                "cfg": actual_cfg,
            },
            "class_type": "CFGGuider",
        }
        guider_ref = [guider_id, 0]
        node_id += 1

        samp_id = str(node_id)
        workflow[samp_id] = {
            "_meta": {"title": "Sampler Advanced"},
            "inputs": {
                "noise": noise_ref,
                "guider": guider_ref,
                "sampler": sampler_ref,
                "sigmas": sigmas_ref,
                "latent_image": latent_ref,
            },
            "class_type": "SamplerCustomAdvanced",
        }
        sampler_output_ref = [samp_id, 0]
        node_id += 1

    # ── VAEDecode ──
    decode_id = str(node_id)
    workflow[decode_id] = {
        "_meta": {"title": "VAE Decode"},
        "inputs": {"samples": sampler_output_ref, "vae": vae_ref},
        "class_type": "VAEDecode",
    }
    frames_ref = [decode_id, 0]
    node_id += 1

    save_id = str(node_id)
    workflow[save_id] = {
        "_meta": {"title": "Save Video"},
        "inputs": {
            "images": frames_ref,
            "filename_prefix": "KAS_video",
            "fps": fps,
            "lossless": webp_lossless,
            "quality": 100 if webp_lossless else 90,
            "method": "default",
        },
        "class_type": "SaveAnimatedWEBP",
    }

    return workflow

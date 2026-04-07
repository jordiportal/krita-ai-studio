"""
Workflow generator que replica EXACTAMENTE el comportamiento de krita-ai-diffusion.

Trazado del código fuente del plugin:
  workflow.py:generate() → comfy_workflow.py:sampler_custom_advanced()

Para Illustrious (Arch.illu, epsilon prediction):
  - Sampler: euler_ancestral (preset "Alternative - Euler A")
  - Scheduler: normal
  - Steps: 24
  - CFG: 5.0
  - Style prompt: "{prompt}, masterpiece, best quality, recent, newest, absurdres, highres"
  - Negative prompt: "nsfw, explicit, worst quality, ..."
  - RescaleCFG: NO (solo para illu_v / v-prediction)
  - Nodos: SamplerCustomAdvanced + CFGGuider + BasicScheduler + RandomNoise + KSamplerSelect
  - Latent: EmptyLatentImage (no EmptySD3LatentImage)
  - Decode: VAEDecode
  - Output: ETN_SaveImageCache
"""

import re
from typing import Dict, Any, List, Tuple


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


MODEL_CONFIGS = {
    "illustrious": {
        "sampler": "euler_ancestral",
        "scheduler": "normal",
        "steps": 24,
        "cfg": 5.0,
        "style_prompt": "{prompt}, masterpiece, best quality, recent, newest, absurdres, highres",
        "negative_prompt": "nsfw, explicit, worst quality, worst aesthetic, bad quality, average quality, oldest, old, very displeasing, displeasing",
        "rescale_cfg": False,
        "is_flux": False,
        "is_sd3": False,
    },
    "sdxl": {
        "sampler": "dpmpp_2m",
        "scheduler": "karras",
        "steps": 20,
        "cfg": 7.0,
        "style_prompt": "{prompt}",
        "negative_prompt": "",
        "rescale_cfg": False,
        "is_flux": False,
        "is_sd3": False,
    },
    "flux": {
        "sampler": "euler",
        "scheduler": "simple",
        "steps": 20,
        "cfg": 1.0,
        "style_prompt": "{prompt}",
        "negative_prompt": "",
        "rescale_cfg": False,
        "is_flux": True,
        "is_sd3": False,
    },
    "sd3": {
        "sampler": "dpmpp_2m",
        "scheduler": "sgm_uniform",
        "steps": 24,
        "cfg": 5.0,
        "style_prompt": "{prompt}",
        "negative_prompt": "",
        "rescale_cfg": False,
        "is_flux": False,
        "is_sd3": True,
    },
    "sd15": {
        "sampler": "dpmpp_2m",
        "scheduler": "karras",
        "steps": 20,
        "cfg": 7.0,
        "style_prompt": "{prompt}",
        "negative_prompt": "",
        "rescale_cfg": False,
        "is_flux": False,
        "is_sd3": False,
    },
}


def detect_model_type(checkpoint_name: str) -> str:
    name = checkpoint_name.lower()
    if "illustrious" in name or "illu" in name or "noobai" in name:
        return "illustrious"
    if "flux" in name:
        return "flux"
    if "sd3" in name or "stable_diffusion_3" in name:
        return "sd3"
    if "xl" in name or "sdxl" in name:
        return "sdxl"
    return "sd15"


def create_txt2img_workflow_krita(
    prompt: str,
    negative_prompt: str = "",
    checkpoint: str = "SDXL.safetensors",
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
    Crea un workflow txt2img que replica EXACTAMENTE el de krita-ai-diffusion.

    Si no se pasan sampler/scheduler/steps/cfg, se usan los del estilo del modelo.
    """

    model_type = detect_model_type(checkpoint)
    config = MODEL_CONFIGS.get(model_type, MODEL_CONFIGS["sdxl"])

    actual_sampler = sampler if sampler else config["sampler"]
    actual_scheduler = scheduler if scheduler else config["scheduler"]
    actual_steps = steps if steps > 0 else config["steps"]
    actual_cfg = cfg if cfg > 0 else config["cfg"]
    is_flux = config["is_flux"]
    is_sd3 = config["is_sd3"]

    final_prompt = config["style_prompt"].replace("{prompt}", prompt)
    final_negative = negative_prompt if negative_prompt else config["negative_prompt"]

    workflow: Dict[str, Any] = {}
    node_id = 1

    # ── 1. CheckpointLoaderSimple ──
    checkpoint_id = str(node_id)
    workflow[checkpoint_id] = {
        "_meta": {"title": "Checkpoint"},
        "inputs": {"ckpt_name": checkpoint},
        "class_type": "CheckpointLoaderSimple",
    }
    model_ref = [checkpoint_id, 0]
    clip_ref = [checkpoint_id, 1]
    vae_ref = [checkpoint_id, 2]
    node_id += 1

    # ── 1b. LoRA Loaders (encadenados) ──
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

    # ── 2. CLIPTextEncode (Positive) ──
    positive_id = str(node_id)
    workflow[positive_id] = {
        "_meta": {"title": "Positive Prompt"},
        "inputs": {
            "text": final_prompt,
            "clip": clip_ref,
        },
        "class_type": "CLIPTextEncode",
    }
    positive_ref = [positive_id, 0]
    node_id += 1

    # ── 3. CLIPTextEncode (Negative) / ConditioningZeroOut ──
    if final_negative and final_negative.strip() and not is_flux:
        negative_id = str(node_id)
        workflow[negative_id] = {
            "_meta": {"title": "Negative Prompt"},
            "inputs": {
                "text": final_negative,
                "clip": clip_ref,
            },
            "class_type": "CLIPTextEncode",
        }
        negative_ref = [negative_id, 0]
        node_id += 1
    else:
        negative_id = str(node_id)
        workflow[negative_id] = {
            "_meta": {"title": "Zero Conditioning"},
            "inputs": {
                "conditioning": positive_ref,
            },
            "class_type": "ConditioningZeroOut",
        }
        negative_ref = [negative_id, 0]
        node_id += 1

    # ── 4. EmptyLatentImage ──
    latent_id = str(node_id)
    if is_flux or is_sd3:
        workflow[latent_id] = {
            "_meta": {"title": "Empty Latent"},
            "inputs": {"width": width, "height": height, "batch_size": batch_size},
            "class_type": "EmptySD3LatentImage",
        }
    else:
        workflow[latent_id] = {
            "_meta": {"title": "Empty Latent"},
            "inputs": {"width": width, "height": height, "batch_size": batch_size},
            "class_type": "EmptyLatentImage",
        }
    latent_ref = [latent_id, 0]
    node_id += 1

    # ── 5. RandomNoise ──
    noise_id = str(node_id)
    workflow[noise_id] = {
        "_meta": {"title": "Random Noise"},
        "inputs": {"noise_seed": seed},
        "class_type": "RandomNoise",
    }
    noise_ref = [noise_id, 0]
    node_id += 1

    # ── 6. KSamplerSelect ──
    sampler_select_id = str(node_id)
    workflow[sampler_select_id] = {
        "_meta": {"title": "Sampler"},
        "inputs": {"sampler_name": actual_sampler},
        "class_type": "KSamplerSelect",
    }
    sampler_ref = [sampler_select_id, 0]
    node_id += 1

    # ── 7. BasicScheduler ──
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

    # ── 8. Guider (CFGGuider para modelos con CFG, BasicGuider para Flux) ──
    guider_id = str(node_id)
    if is_flux:
        flux_guid_id = str(node_id)
        workflow[flux_guid_id] = {
            "_meta": {"title": "Flux Guidance"},
            "inputs": {
                "conditioning": positive_ref,
                "guidance": 3.5 if actual_cfg <= 1 else actual_cfg,
            },
            "class_type": "FluxGuidance",
        }
        flux_positive_ref = [flux_guid_id, 0]
        node_id += 1

        guider_id = str(node_id)
        workflow[guider_id] = {
            "_meta": {"title": "Guider"},
            "inputs": {
                "model": model_ref,
                "conditioning": flux_positive_ref,
            },
            "class_type": "BasicGuider",
        }
    elif actual_cfg == 1.0:
        workflow[guider_id] = {
            "_meta": {"title": "Guider"},
            "inputs": {
                "model": model_ref,
                "conditioning": positive_ref,
            },
            "class_type": "BasicGuider",
        }
    else:
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

    # ── 9. SamplerCustomAdvanced ──
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
    # SamplerCustomAdvanced output[0]=output, output[1]=denoised_output
    # Krita usa output[1] (denoised_output) para VAEDecode
    sampler_output_ref = [sampler_adv_id, 1]
    node_id += 1

    # ── 10. VAEDecode ──
    decode_id = str(node_id)
    workflow[decode_id] = {
        "_meta": {"title": "VAE Decode"},
        "inputs": {
            "samples": sampler_output_ref,
            "vae": vae_ref,
        },
        "class_type": "VAEDecode",
    }
    image_ref = [decode_id, 0]
    node_id += 1

    # ── 11. ETN_SaveImageCache ──
    cache_id = str(node_id)
    workflow[cache_id] = {
        "_meta": {"title": "Save to Cache"},
        "inputs": {
            "images": image_ref,
            "format": "PNG",
        },
        "class_type": "ETN_SaveImageCache",
    }

    return workflow


def create_txt2video_workflow(
    prompt: str,
    negative_prompt: str = "",
    checkpoint: str = "wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors",
    vae: str = "wan_2.1_vae.safetensors",
    clip: str = "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
    sampler: str = "",
    scheduler: str = "",
    steps: int = 20,
    cfg: float = 7.0,
    seed: int = -1,
    width: int = 832,
    height: int = 480,
    length: int = 81,
    fps: float = 8.0,
    batch_size: int = 1,
) -> Dict[str, Any]:
    """
    Crea un workflow txt2video usando Wan 2.1 T2V.

    Wan 2.1 requiere:
    - UNet especifico (Wan 2.1 T2V)
    - VAE de Wan (16 canales, compresion temporal)
    - Text encoder UMT5

    Nodos principales:
    - UNETLoader (type=wan)
    - VAELoader
    - CLIPLoader (type=wan / t5)
    - CLIPTextEncode x2
    - WanImageToVideo (sin imagen inicial = T2V puro)
    - RandomNoise + KSamplerSelect + BasicScheduler
    - SamplerCustomAdvanced + VAEDecode
    - KAS_SaveVideoCache (nuestro nodo de cache)
    """

    # Defaults para Wan T2V
    actual_sampler = sampler if sampler else "euler_ancestral"
    actual_scheduler = scheduler if scheduler else "normal"
    actual_steps = steps if steps > 0 else 20
    actual_cfg = cfg if cfg > 0 else 7.0

    workflow: Dict[str, Any] = {}
    node_id = 1

    # ── 1. UNETLoader (para Wan 2.x) ──
    unet_id = str(node_id)
    workflow[unet_id] = {
        "_meta": {"title": "Wan UNET"},
        "inputs": {"unet_name": checkpoint, "weight_dtype": "default"},
        "class_type": "UNETLoader",
    }
    model_ref = [unet_id, 0]
    node_id += 1

    # ── 2. CLIPLoader (para UMT5 / Wan text encoder) ──
    clip_id = str(node_id)
    workflow[clip_id] = {
        "_meta": {"title": "Wan CLIP"},
        "inputs": {"clip_name": clip, "type": "wan"},
        "class_type": "CLIPLoader",
    }
    clip_ref = [clip_id, 0]
    node_id += 1

    # ── 3. VAELoader (para Wan VAE) ──
    vae_id = str(node_id)
    workflow[vae_id] = {
        "_meta": {"title": "Wan VAE"},
        "inputs": {"vae_name": vae},
        "class_type": "VAELoader",
    }
    vae_ref = [vae_id, 0]
    node_id += 1

    # ── 4. CLIPTextEncode (Positive) ──
    positive_id = str(node_id)
    workflow[positive_id] = {
        "_meta": {"title": "Positive Prompt"},
        "inputs": {
            "text": prompt,
            "clip": clip_ref,
        },
        "class_type": "CLIPTextEncode",
    }
    positive_ref = [positive_id, 0]
    node_id += 1

    # ── 5. CLIPTextEncode (Negative) ──
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

    # ── 6. WanImageToVideo (latent + conditioning para T2V) ──
    # Sin start_image = Text-to-Video puro
    wan_latent_id = str(node_id)
    workflow[wan_latent_id] = {
        "_meta": {"title": "Wan T2V Latent"},
        "inputs": {
            "positive": positive_ref,
            "negative": negative_ref,
            "vae": vae_ref,
            "width": width,
            "height": height,
            "length": length,  # Frames del video
            "batch_size": batch_size,
        },
        "class_type": "WanImageToVideo",
    }
    latent_ref = [wan_latent_id, 2]  # Output 2 = latent
    positive_cond_ref = [wan_latent_id, 0]  # Output 0 = positive conditioned
    negative_cond_ref = [wan_latent_id, 1]  # Output 1 = negative conditioned
    node_id += 1

    # ── 7. RandomNoise ──
    noise_id = str(node_id)
    workflow[noise_id] = {
        "_meta": {"title": "Random Noise"},
        "inputs": {"noise_seed": seed},
        "class_type": "RandomNoise",
    }
    noise_ref = [noise_id, 0]
    node_id += 1

    # ── 8. KSamplerSelect ──
    sampler_select_id = str(node_id)
    workflow[sampler_select_id] = {
        "_meta": {"title": "Sampler"},
        "inputs": {"sampler_name": actual_sampler},
        "class_type": "KSamplerSelect",
    }
    sampler_ref = [sampler_select_id, 0]
    node_id += 1

    # ── 9. BasicScheduler ──
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

    # ── 10. CFGGuider ──
    guider_id = str(node_id)
    workflow[guider_id] = {
        "_meta": {"title": "CFG Guider"},
        "inputs": {
            "model": model_ref,
            "positive": positive_cond_ref,
            "negative": negative_cond_ref,
            "cfg": actual_cfg,
        },
        "class_type": "CFGGuider",
    }
    guider_ref = [guider_id, 0]
    node_id += 1

    # ── 11. SamplerCustomAdvanced ──
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
    # Output[1] = denoised_output
    sampler_output_ref = [sampler_adv_id, 1]
    node_id += 1

    # ── 12. VAEDecode ──
    decode_id = str(node_id)
    workflow[decode_id] = {
        "_meta": {"title": "VAE Decode"},
        "inputs": {
            "samples": sampler_output_ref,
            "vae": vae_ref,
        },
        "class_type": "VAEDecode",
    }
    frames_ref = [decode_id, 0]
    node_id += 1

    # ── 13. KAS_SaveVideoCache ──
    # Nuestro nodo para guardar frames como video en cache
    video_cache_id = str(node_id)
    workflow[video_cache_id] = {
        "_meta": {"title": "Save Video Cache"},
        "inputs": {
            "images": frames_ref,
            "fps": fps,
            "format": "webm",
            "quality": "medium",
        },
        "class_type": "KAS_SaveVideoCache",
    }

    return workflow

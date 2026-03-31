export interface ComfyStatus {
  status: string;
  comfyui: string;
  comfyui_url: string;
}

export interface Model {
  name: string;
  type: string;
}

export interface ModelList {
  checkpoints: Model[] | string[];
  loras: Model[] | string[];
  controlnets: Model[] | string[];
}

export interface SamplerList {
  samplers: string[];
}

export interface GenerationRequest {
  prompt: string;
  negative_prompt?: string;
  width: number;
  height: number;
  steps: number;
  cfg_scale: number;
  sampler: string;
  checkpoint?: string;
  seed: number;
  strength?: number;
}

export interface GenerationResponse {
  job_id: string;
  status: string;
  images?: string[];
  error?: string;
}

export interface JobStatus {
  job_id: string;
  status: string;
  progress?: number;
  error?: string;
  images?: string[];
}

export interface Settings {
  [key: string]: string | undefined;
  checkpoint?: string;
  sampler?: string;
  scheduler?: string;
  steps?: string;
  cfg?: string;
  width?: string;
  height?: string;
  negative_prompt?: string;
  strength?: string;
}

export interface ComfyConfig {
  comfyui_host: string;
  comfyui_port: string;
  comfyui_secure: string;
  comfyui_url?: string;
}

export interface ConnectionTestResult {
  status: string;
  url: string;
  message: string;
  vram_gb?: number;
}

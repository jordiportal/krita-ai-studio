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
  diffusion_models?: Model[] | string[];
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
  model_type?: string;
  seed: number;
  strength?: number;
}

export interface GenerationVideoRequest {
  prompt: string;
  negative_prompt?: string;
  width: number;
  height: number;
  length: number;
  fps: number;
  steps: number;
  cfg_scale: number;
  sampler: string;
  checkpoint?: string;
  vae?: string;
  clip?: string;
  seed: number;
}

export interface MissingLoraCandidate {
  civitai_model_id: number;
  civitai_version_id: number;
  name: string;
  filename: string;
  size_bytes: number;
  download_url: string;
  base_model: string;
  thumbnail: string;
  download_count: number;
  rating: number;
}

export interface MissingLoraResult {
  lora_tag: string;
  strength_model: number;
  strength_clip: number;
  candidates: MissingLoraCandidate[];
}

export interface GenerationResponse {
  job_id: string;
  status: string;
  images?: string[];
  videos?: string[];
  video_ids?: string[];
  is_video?: boolean;
  error?: string;
  missing_loras?: MissingLoraResult[];
}

export interface JobStatus {
  job_id: string;
  status: string;
  progress?: number;
  error?: string;
  images?: string[];
  videos?: string[];
  video_ids?: string[];
  is_video?: boolean;
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
  auth_user?: string;
  auth_pass?: string;
  civitai_api_key?: string;
  civitai_nsfw_level?: string;
}

export interface ConnectionTestResult {
  status: string;
  url: string;
  message: string;
  vram_gb?: number;
}

export interface GalleryItem {
  id: string;
  prompt: string;
  neg_prompt: string;
  checkpoint: string;
  width: number;
  height: number;
  filename: string;
  created_at: number;
  type?: string;
  length?: number;
  fps?: number;
}

export interface VideoModel {
  name: string;
  filename: string;
  size_bytes: number;
  architecture: string;
  architecture_label: string;
}

export interface GalleryResponse {
  items: GalleryItem[];
  total: number;
}

export interface AuthStatus {
  auth_enabled: boolean;
  logged_in: boolean;
  username?: string;
}

export interface LoginResponse {
  token: string;
  username: string;
}

export interface CachedModel {
  id: string;
  civitai_model_id: number;
  civitai_version_id: number;
  name: string;
  type: string;
  filename: string;
  size_bytes: number;
  downloaded_at: number;
  status: string;
  progress: number;
  download_url: string;
  metadata: string;
  speed?: number;
  downloaded?: number;
}

export interface CacheResponse {
  items: CachedModel[];
}

export interface ModelTypeOption {
  label: string;
  value: string;
}

export interface InventoryItem {
  filename: string;
  folder: string;
  size_bytes: number;
  base_model: string;
  architecture: string;
  architecture_label: string;
  has_override: boolean;
  from_civitai: boolean;
  civitai_name: string | null;
  civitai_model_id: number | null;
}

export interface InventoryCategory {
  key: string;
  label: string;
  icon: string;
  items: InventoryItem[];
  count: number;
  total_bytes: number;
}

export interface InventoryResponse {
  categories: InventoryCategory[];
  total_files: number;
  total_bytes: number;
  active_downloads: CachedModel[];
}

export interface ArchitectureSampling {
  sampler: string;
  scheduler: string;
  steps: number;
  cfg: number;
}

export interface ArchitectureClip {
  mode: string;
  type?: string;
  clip1?: string;
  clip2?: string;
}

export interface ArchitectureGuidance {
  type: string;
  default?: number;
}

export interface Architecture {
  id: string;
  label: string;
  detection: string[];
  exclude: string[];
  require?: string[];
  priority: number;
  loader: string;
  clip: ArchitectureClip;
  vae: string | null;
  weight_dtype?: string;
  latent_node: string;
  guidance: ArchitectureGuidance;
  sampling: ArchitectureSampling;
  prompt: { style: string; negative: string };
  rescale_cfg: boolean;
  capabilities: string[];
  hidden_from: string[];
}

export interface ArchitecturesResponse {
  architectures: Architecture[];
}

export interface ModelOverride {
  filename: string;
  architecture: string | null;
  sampling: Partial<ArchitectureSampling>;
  clip: Partial<ArchitectureClip>;
  vae: string | null;
  hidden: number;
  notes: string;
}

export interface ModelOverrideResponse {
  filename: string;
  override: ModelOverride | null;
}

export interface ModelOverridesListResponse {
  overrides: ModelOverride[];
}

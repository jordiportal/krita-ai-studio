import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import {
  ComfyStatus,
  ModelList,
  SamplerList,
  GenerationRequest,
  GenerationVideoRequest,
  GenerationResponse,
  JobStatus,
  Settings,
  ComfyConfig,
  ConnectionTestResult,
  LlmTestResult,
  PromptEnhanceResponse,
  GalleryResponse,
  CacheResponse,
  InventoryResponse,
  ModelFavoritesResponse,
  ModelFavoritePutPayload,
  WorkflowsListResponse,
  ArchitecturesResponse,
  ModelOverrideResponse,
  ModelOverridesListResponse,
  UsersListResponse,
  AppUserRow,
} from './types';

@Injectable({
  providedIn: 'root',
})
export class GenerationService {
  private apiUrl = '/api';

  constructor(private http: HttpClient) {}

  getHealth(): Observable<ComfyStatus> {
    return this.http.get<ComfyStatus>(`${this.apiUrl}/health`);
  }

  getModels(): Observable<ModelList> {
    return this.http.get<ModelList>(`${this.apiUrl}/models`);
  }

  getSamplers(): Observable<SamplerList> {
    return this.http.get<SamplerList>(`${this.apiUrl}/samplers`);
  }

  getSettings(): Observable<Settings> {
    return this.http.get<Settings>(`${this.apiUrl}/settings`);
  }

  saveSettings(data: Record<string, any>): Observable<Settings> {
    return this.http.post<Settings>(`${this.apiUrl}/settings`, data);
  }

  getConfig(): Observable<ComfyConfig> {
    return this.http.get<ComfyConfig>(`${this.apiUrl}/config`);
  }

  saveConfig(data: Partial<ComfyConfig>): Observable<ComfyConfig> {
    return this.http.post<ComfyConfig>(`${this.apiUrl}/config`, data);
  }

  testConnection(data: Partial<ComfyConfig>): Observable<ConnectionTestResult> {
    return this.http.post<ConnectionTestResult>(`${this.apiUrl}/config/test`, data);
  }

  testLlm(data: Partial<ComfyConfig>): Observable<LlmTestResult> {
    return this.http.post<LlmTestResult>(`${this.apiUrl}/llm/test`, data);
  }

  enhancePrompt(prompt: string): Observable<PromptEnhanceResponse> {
    return this.http.post<PromptEnhanceResponse>(`${this.apiUrl}/prompt/enhance`, { prompt });
  }

  generateTxt2Img(request: GenerationRequest): Observable<GenerationResponse> {
    return this.http.post<GenerationResponse>(
      `${this.apiUrl}/generate/txt2img`,
      request
    );
  }

  generateTxt2Video(request: GenerationVideoRequest): Observable<GenerationResponse> {
    return this.http.post<GenerationResponse>(
      `${this.apiUrl}/generate/txt2video`,
      request
    );
  }

  generateTxt2VideoXdit(request: GenerationVideoRequest): Observable<GenerationResponse> {
    return this.http.post<GenerationResponse>(
      `${this.apiUrl}/generate/txt2video-xdit`,
      request
    );
  }

  generateImg2VideoXdit(request: { gallery_id: string; prompt?: string; negative_prompt?: string; length?: number; fps?: number; steps?: number; cfg_scale?: number; seed?: number }): Observable<GenerationResponse> {
    return this.http.post<GenerationResponse>(
      `${this.apiUrl}/generate/img2video-xdit`,
      request
    );
  }

  getXditHealth(): Observable<any> {
    return this.http.get(`${this.apiUrl}/xdit/health`);
  }

  getVideoUrl(videoId: string): string {
    return `${this.apiUrl}/video/${videoId}`;
  }

  getJobStatus(jobId: string): Observable<JobStatus> {
    return this.http.get<JobStatus>(`${this.apiUrl}/jobs/${jobId}`);
  }

  getGallery(limit: number = 50, offset: number = 0): Observable<GalleryResponse> {
    return this.http.get<GalleryResponse>(
      `${this.apiUrl}/gallery?limit=${limit}&offset=${offset}`
    );
  }

  getGalleryImageUrl(imgId: string): string {
    return `${this.apiUrl}/gallery/${imgId}/image`;
  }

  deleteGalleryImage(imgId: string): Observable<any> {
    return this.http.delete(`${this.apiUrl}/gallery/${imgId}`);
  }

  searchCivitai(params: Record<string, string | number | boolean>): Observable<any> {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== '' && v !== undefined) qs.set(k, String(v));
    }
    return this.http.get(`${this.apiUrl}/civitai/search?${qs.toString()}`);
  }

  getCivitaiModel(modelId: number): Observable<any> {
    return this.http.get(`${this.apiUrl}/civitai/models/${modelId}`);
  }

  downloadModel(data: any): Observable<any> {
    return this.http.post(`${this.apiUrl}/civitai/download`, data);
  }

  getDownloads(): Observable<any> {
    return this.http.get(`${this.apiUrl}/civitai/downloads`);
  }

  getCache(): Observable<CacheResponse> {
    return this.http.get<CacheResponse>(`${this.apiUrl}/cache`);
  }

  deleteCacheItem(id: string): Observable<any> {
    return this.http.delete(`${this.apiUrl}/cache/${id}`);
  }

  getCivitaiVersionImages(versionId: number, limit: number = 20): Observable<any> {
    return this.http.get(`${this.apiUrl}/civitai/version-images/${versionId}?limit=${limit}`);
  }

  browseCivitaiImages(params: Record<string, string | number>): Observable<any> {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== '' && v !== undefined && v !== 0) qs.set(k, String(v));
    }
    return this.http.get(`${this.apiUrl}/civitai/images?${qs.toString()}`);
  }

  getGalleryImageMeta(imgId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/gallery/${imgId}/meta`);
  }

  downloadLora(data: any): Observable<any> {
    return this.http.post(`${this.apiUrl}/lora/download`, data);
  }

  getLoraDownloadStatus(downloadId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/lora/download-status/${encodeURIComponent(downloadId)}`);
  }

  getInventory(): Observable<InventoryResponse> {
    return this.http.get<InventoryResponse>(`${this.apiUrl}/inventory`);
  }

  getWorkflows(): Observable<WorkflowsListResponse> {
    return this.http.get<WorkflowsListResponse>(`${this.apiUrl}/workflows`);
  }

  getModelFavorites(): Observable<ModelFavoritesResponse> {
    return this.http.get<ModelFavoritesResponse>(`${this.apiUrl}/model-favorites`);
  }

  putModelFavorite(data: ModelFavoritePutPayload): Observable<{ status: string }> {
    return this.http.put<{ status: string }>(`${this.apiUrl}/model-favorites`, data);
  }

  deleteModelFavorite(folder: string, filename: string): Observable<{ status: string }> {
    return this.http.delete<{ status: string }>(
      `${this.apiUrl}/model-favorites/${encodeURIComponent(folder)}/${encodeURIComponent(filename)}`
    );
  }

  deleteInventoryModel(folder: string, filename: string): Observable<any> {
    return this.http.delete(`${this.apiUrl}/inventory/${encodeURIComponent(folder)}/${encodeURIComponent(filename)}`);
  }

  getArchitectures(): Observable<ArchitecturesResponse> {
    return this.http.get<ArchitecturesResponse>(`${this.apiUrl}/architectures`);
  }

  getModelOverride(filename: string): Observable<ModelOverrideResponse> {
    return this.http.get<ModelOverrideResponse>(`${this.apiUrl}/model-overrides/${encodeURIComponent(filename)}`);
  }

  saveModelOverride(filename: string, data: Record<string, any>): Observable<any> {
    return this.http.post(`${this.apiUrl}/model-overrides/${encodeURIComponent(filename)}`, data);
  }

  deleteModelOverride(filename: string): Observable<any> {
    return this.http.delete(`${this.apiUrl}/model-overrides/${encodeURIComponent(filename)}`);
  }

  getModelOverrides(): Observable<ModelOverridesListResponse> {
    return this.http.get<ModelOverridesListResponse>(`${this.apiUrl}/model-overrides`);
  }

  getVideoModels(): Observable<{ models: import('./types').VideoModel[] }> {
    return this.http.get<{ models: import('./types').VideoModel[] }>(`${this.apiUrl}/video-models`);
  }

  getUsers(): Observable<UsersListResponse> {
    return this.http.get<UsersListResponse>(`${this.apiUrl}/users`);
  }

  patchUser(
    userId: string,
    body: { role?: string; disabled?: boolean },
  ): Observable<{ user: AppUserRow }> {
    return this.http.patch<{ user: AppUserRow }>(
      `${this.apiUrl}/users/${encodeURIComponent(userId)}`,
      body,
    );
  }
}

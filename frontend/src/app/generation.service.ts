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
  GalleryResponse,
  CacheResponse,
  InventoryResponse,
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

  getInventory(): Observable<InventoryResponse> {
    return this.http.get<InventoryResponse>(`${this.apiUrl}/inventory`);
  }

  deleteInventoryModel(folder: string, filename: string): Observable<any> {
    return this.http.delete(`${this.apiUrl}/inventory/${encodeURIComponent(folder)}/${encodeURIComponent(filename)}`);
  }
}

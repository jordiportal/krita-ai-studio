import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import {
  ComfyStatus,
  ModelList,
  SamplerList,
  GenerationRequest,
  GenerationResponse,
  JobStatus,
  Settings,
  ComfyConfig,
  ConnectionTestResult,
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

  getJobStatus(jobId: string): Observable<JobStatus> {
    return this.http.get<JobStatus>(`${this.apiUrl}/jobs/${jobId}`);
  }
}

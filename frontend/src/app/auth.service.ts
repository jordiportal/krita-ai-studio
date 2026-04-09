import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, Subject, tap } from 'rxjs';
import { AuthStatus, LoginResponse } from './types';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly TOKEN_KEY = 'krita_ai_token';
  private readonly apiUrl = '/api';
  private logoutSubject = new Subject<void>();
  readonly sessionExpired$ = this.logoutSubject.asObservable();

  constructor(private http: HttpClient) {}

  checkStatus(): Observable<AuthStatus> {
    return this.http.get<AuthStatus>('/api/auth/status');
  }

  login(username: string, password: string): Observable<LoginResponse> {
    return this.http.post<LoginResponse>('/api/auth/login', { username, password }).pipe(
      tap(res => this.setToken(res.token))
    );
  }

  logout(onDone?: () => void): void {
    this.http.post<{ status: string }>(`${this.apiUrl}/auth/logout`, {}).subscribe({
      next: () => {
        localStorage.removeItem(this.TOKEN_KEY);
        this.logoutSubject.next();
        onDone?.();
      },
      error: () => {
        localStorage.removeItem(this.TOKEN_KEY);
        this.logoutSubject.next();
        onDone?.();
      },
    });
  }

  loginWithMicrosoft(): void {
    window.location.href = `${this.apiUrl}/auth/microsoft/start`;
  }

  getToken(): string | null {
    return localStorage.getItem(this.TOKEN_KEY);
  }

  setToken(token: string): void {
    localStorage.setItem(this.TOKEN_KEY, token);
  }

  getAuthenticatedUrl(url: string): string {
    const token = this.getToken();
    if (!token) return url;
    const sep = url.includes('?') ? '&' : '?';
    return `${url}${sep}token=${token}`;
  }
}

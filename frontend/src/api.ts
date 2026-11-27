import type {
  CompareResponse,
  GpaEstimate,
  Program,
  ProgramSummary,
  Rule,
  StudentProfile,
} from './types'

const TOKEN_KEY = 'gdufe_transfer_token'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
  })
  if (!response.ok) {
    let message = `请求失败（${response.status}）`
    try {
      const body = await response.json()
      message = body.detail || body.message || message
    } catch {
      /* ignore */
    }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

export const api = {
  getStoredToken: () => sessionStorage.getItem(TOKEN_KEY) || '',
  storeToken: (token: string) => sessionStorage.setItem(TOKEN_KEY, token),
  clearToken: () => sessionStorage.removeItem(TOKEN_KEY),

  health: () => request<{ ok: boolean }>('/api/health'),
  demoPrograms: () => request<ProgramSummary[]>('/api/demo/programs'),
  demoProgram: (major: string, grade: number) =>
    request<Program>(`/api/demo/programs/${encodeURIComponent(major)}?grade=${grade}`),
  rules: () => request<Rule[]>('/api/rules'),

  transferStats: () => request<{
    title: string; year: number; note: string
    records: { seq: number; from_major: string; to_major: string; category: string; choice: string; gpa: number }[]
    summary: Record<string, { count: number; min: number; p25: number; median: number; p75: number; max: number }>
  }>('/api/transfer-stats'),

  gpaEstimate: (gpa: number, targetMajors: string[]) =>
    request<{ gpa: number; note: string; items: GpaEstimate[] }>('/api/gpa-estimate', {
      method: 'POST',
      body: JSON.stringify({ gpa, target_majors: targetMajors }),
    }),

  captcha: (captchaId?: string) =>
    request<{ captcha_id: string; image: string }>('/api/auth/captcha', {
      method: 'POST',
      body: JSON.stringify({ captcha_id: captchaId || null }),
    }),

  login: (captchaId: string, username: string, password: string, captcha: string) =>
    request<{
      ok: boolean
      message: string
      token?: string
      profile?: StudentProfile
      captcha_id?: string
    }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ captcha_id: captchaId, username, password, captcha }),
    }),

  me: (token: string) =>
    request<StudentProfile>(`/api/me?token=${encodeURIComponent(token)}`),

  programOptions: (token: string) =>
    request<Record<string, string[]>>(
      `/api/programs/options?token=${encodeURIComponent(token)}`,
    ),

  programColleges: (token: string) =>
    request<{ colleges: { value: string; label: string }[] }>(
      `/api/programs/colleges?token=${encodeURIComponent(token)}`,
    ),

  programMajors: (token: string, college: string, grade: number) =>
    request<{ majors: string[]; college: string }>(
      `/api/programs/majors?token=${encodeURIComponent(token)}&college=${encodeURIComponent(college)}&grade=${grade}`,
    ),

  liveProgram: (token: string, major: string, grade: number) =>
    request<Program>(
      `/api/programs/live?token=${encodeURIComponent(token)}&major=${encodeURIComponent(major)}&grade=${grade}`,
    ),

  importProgram: (major: string, grade: number, html: string) =>
    request<Program>('/api/programs/import', {
      method: 'POST',
      body: JSON.stringify({ major, grade, html }),
    }),

  compare: (payload: {
    profile: StudentProfile
    current_major: string
    target_majors: string[]
    grade: number
    source: 'demo' | 'live' | 'import'
    token?: string
    major_colleges?: Record<string, string>
    imported_programs?: Program[]
    rules?: Rule[]
  }) => request<CompareResponse>('/api/compare', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
}

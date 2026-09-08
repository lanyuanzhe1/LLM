import { withBasePath } from './base-path'

export type SessionUser = {
  token: string
  token_type: string
  expires_at?: number | null
  id: string
  email: string
  name: string
  role: string
  profile_image_url?: string
  permissions?: Record<string, unknown>
}

type Fetcher = typeof fetch

const parseAuthResponse = async (response: Response): Promise<SessionUser> => {
  const payload = (await response.json().catch(() => ({}))) as Partial<SessionUser> & { detail?: string }

  if (!response.ok) {
    throw new Error(payload.detail || '认证服务暂时不可用，请稍后重试')
  }

  return payload as SessionUser
}

const postAuth = async (
  path: 'signin' | 'signup',
  body: Record<string, string>,
  fetcher: Fetcher,
  basePath: string
) => {
  const response = await fetcher(withBasePath(`/api/auths/${path}`, basePath), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })

  return parseAuthResponse(response)
}

export const signin = (
  email: string,
  password: string,
  fetcher: Fetcher = fetch,
  basePath = process.env.NEXT_PUBLIC_BASE_PATH || ''
) => postAuth('signin', { email, password }, fetcher, basePath)

export const signup = (
  name: string,
  email: string,
  password: string,
  fetcher: Fetcher = fetch,
  basePath = process.env.NEXT_PUBLIC_BASE_PATH || ''
) => postAuth('signup', { name, email, password }, fetcher, basePath)

export const validateSession = async (
  token: string | null,
  fetcher: Fetcher = fetch,
  basePath = process.env.NEXT_PUBLIC_BASE_PATH || ''
) => {
  const headers = token ? { Authorization: `Bearer ${token}` } : undefined
  const response = await fetcher(withBasePath('/api/auths/me', basePath), { headers })

  return parseAuthResponse(response)
}

export const signout = async (
  token: string | null,
  fetcher: Fetcher = fetch,
  basePath = process.env.NEXT_PUBLIC_BASE_PATH || ''
) => {
  const headers = token ? { Authorization: `Bearer ${token}` } : undefined

  const response = await fetcher(withBasePath('/api/auths/signout', basePath), {
    method: 'POST',
    headers,
    credentials: 'same-origin'
  })

  if (!response.ok) throw new Error('退出登录失败，请稍后重试')
}

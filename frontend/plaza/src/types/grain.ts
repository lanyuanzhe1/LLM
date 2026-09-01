export type UserRole = 'student' | 'teacher' | 'researcher' | 'technician'

export type Citation = {
  evidence_id: string
  document_id?: string
  title?: string
  source?: string
  page?: number | null
  section?: string | null
  text?: string
  score?: number | null
  authority_level?: string
}

export type ChatMessage = {
  id: string
  role: 'assistant' | 'user'
  content: string
  citations?: Citation[]
  error?: boolean
  pending?: boolean
}

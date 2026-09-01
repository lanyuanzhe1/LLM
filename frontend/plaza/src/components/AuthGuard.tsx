'use client'

import { useEffect, useState } from 'react'

import { useRouter } from 'next/navigation'

import CircularProgress from '@mui/material/CircularProgress'

import { validateSession } from '@/lib/auth-client'

const AuthGuard = ({ children }: { children: React.ReactNode }) => {
  const router = useRouter()
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let active = true
    const token = window.localStorage.getItem('token')

    validateSession(token)
      .then(session => {
        if (!active) return
        if (session.token) window.localStorage.setItem('token', session.token)
        setReady(true)
      })
      .catch(() => {
        if (!active) return
        window.localStorage.removeItem('token')
        router.replace('/login')
      })

    return () => {
      active = false
    }
  }, [router])

  if (!ready) {
    return (
      <div className='flex min-h-[100dvh] items-center justify-center' aria-live='polite' aria-label='正在验证登录状态'>
        <CircularProgress size={32} />
      </div>
    )
  }

  return children
}

export default AuthGuard

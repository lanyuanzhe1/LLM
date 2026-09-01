'use client'

// React Imports
import { useState } from 'react'
import type { FormEvent } from 'react'

// Next Imports
import Link from 'next/link'
import { useRouter } from 'next/navigation'

// MUI Imports
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Typography from '@mui/material/Typography'
import TextField from '@mui/material/TextField'
import IconButton from '@mui/material/IconButton'
import InputAdornment from '@mui/material/InputAdornment'
import Button from '@mui/material/Button'

// Type Imports
import type { Mode } from '@core/types'

// Component Imports
import Illustrations from '@components/Illustrations'
import Logo from '@components/layout/shared/Logo'

// Hook Imports
import { useImageVariant } from '@core/hooks/useImageVariant'
import { signup } from '@/lib/auth-client'
import { withBasePath } from '@/lib/base-path'

const Register = ({ mode }: { mode: Mode }) => {
  // States
  const [isPasswordShown, setIsPasswordShown] = useState(false)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errorMessage, setErrorMessage] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // Vars
  const darkImg = withBasePath('/images/pages/auth-v1-mask-dark.png')
  const lightImg = withBasePath('/images/pages/auth-v1-mask-light.png')

  // Hooks
  const router = useRouter()
  const authBackground = useImageVariant(mode, lightImg, darkImg)

  const handleClickShowPassword = () => setIsPasswordShown(show => !show)

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (submitting) return

    setErrorMessage('')
    setSubmitting(true)

    try {
      const session = await signup(name.trim(), email.trim(), password)

      window.localStorage.setItem('token', session.token)
      router.replace('/')
      router.refresh()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '注册失败，请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className='flex flex-col justify-center items-center min-bs-[100dvh] relative p-6'>
      <Card className='flex flex-col sm:is-[450px]'>
        <CardContent className='p-6 sm:!p-12'>
          <Link href='/' className='flex justify-center items-start mbe-6'>
            <Logo />
          </Link>
          <Typography variant='h4'>创建账户</Typography>
          <div className='flex flex-col gap-5'>
            <Typography className='mbs-1'>注册后可在两个前端中使用同一登录状态</Typography>
            <form noValidate autoComplete='off' onSubmit={handleSubmit} className='flex flex-col gap-5'>
              <TextField
                autoFocus
                required
                fullWidth
                label='姓名'
                value={name}
                onChange={event => setName(event.target.value)}
              />
              <TextField
                required
                fullWidth
                label='邮箱'
                type='email'
                value={email}
                onChange={event => setEmail(event.target.value)}
              />
              <TextField
                required
                fullWidth
                label='密码'
                type={isPasswordShown ? 'text' : 'password'}
                value={password}
                onChange={event => setPassword(event.target.value)}
                InputProps={{
                  endAdornment: (
                    <InputAdornment position='end'>
                      <IconButton
                        size='small'
                        edge='end'
                        onClick={handleClickShowPassword}
                        onMouseDown={e => e.preventDefault()}
                      >
                        <i className={isPasswordShown ? 'ri-eye-off-line' : 'ri-eye-line'} />
                      </IconButton>
                    </InputAdornment>
                  )
                }}
              />
              {errorMessage ? <Typography color='error'>{errorMessage}</Typography> : null}
              <Button fullWidth variant='contained' type='submit' disabled={submitting}>
                {submitting ? '正在注册…' : '注册'}
              </Button>
              <div className='flex justify-center items-center flex-wrap gap-2'>
                <Typography>已有账户？</Typography>
                <Typography component={Link} href='/login' color='primary'>
                  返回登录
                </Typography>
              </div>
            </form>
          </div>
        </CardContent>
      </Card>
      <Illustrations maskImg={{ src: authBackground }} />
    </div>
  )
}

export default Register

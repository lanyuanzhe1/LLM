'use client'

import { useEffect, useMemo, useRef, useState } from 'react'

import { useSearchParams } from 'next/navigation'

import Accordion from '@mui/material/Accordion'
import AccordionDetails from '@mui/material/AccordionDetails'
import AccordionSummary from '@mui/material/AccordionSummary'
import Alert from '@mui/material/Alert'
import Avatar from '@mui/material/Avatar'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import Divider from '@mui/material/Divider'
import FormControl from '@mui/material/FormControl'
import Grid from '@mui/material/Grid'
import IconButton from '@mui/material/IconButton'
import InputLabel from '@mui/material/InputLabel'
import MenuItem from '@mui/material/MenuItem'
import Select from '@mui/material/Select'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'

import { consumeSse } from '@/lib/consumeSse'
import { withBasePath } from '@/lib/base-path'
import type { ChatMessage, Citation, UserRole } from '@/types/grain'

const welcomeMessage: ChatMessage = {
  id: 'welcome',
  role: 'assistant',
  content:
    '你好，我是粮储智学助手。我会先检索课程资料，再基于证据回答并标注来源。你可以直接提问，也可以从左侧选择学习任务。'
}

const quickPrompts = [
  {
    title: '解释一个概念',
    description: '核心概念 · 机制 · 条件 · 易错点',
    icon: 'ri-lightbulb-flash-line',
    prompt: '请结合课程资料讲解低温储粮的核心概念、作用机制、适用条件和易错点。'
  },
  {
    title: '整理复习提纲',
    description: '提炼关键知识，形成结构化总结',
    icon: 'ri-file-list-3-line',
    prompt: '请基于课程资料总结低温储粮的关键知识点，并给出复习提纲。'
  },
  {
    title: '开始逐题练习',
    description: '先出一道，作答后再反馈',
    icon: 'ri-question-answer-line',
    prompt: '请基于课程资料生成3道由易到难的练习题，先只展示第1道且不要公布答案。'
  },
  {
    title: '制定学习计划',
    description: '根据基础和可用时间安排复习',
    icon: 'ri-calendar-schedule-line',
    prompt: '我想在7天内复习粮食储藏课程，请先询问我的基础和每天可用时间。'
  }
]

const roleLabels: Record<UserRole, string> = {
  student: '学生',
  teacher: '教师',
  researcher: '研究人员',
  technician: '粮库技术人员'
}

const createId = () => crypto.randomUUID()

const ChatWorkspace = () => {
  const searchParams = useSearchParams()
  const [messages, setMessages] = useState<ChatMessage[]>([welcomeMessage])
  const [input, setInput] = useState('')
  const [role, setRole] = useState<UserRole>('student')
  const [sessionId, setSessionId] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const messageListRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const stored = window.localStorage.getItem('grain-learning-session')
    const resolved = stored || createId()

    window.localStorage.setItem('grain-learning-session', resolved)
    setSessionId(resolved)
  }, [])

  useEffect(() => {
    const prompt = searchParams.get('prompt')

    if (prompt) setInput(prompt)
  }, [searchParams])

  useEffect(() => {
    if (messages.length <= 1) return

    const messageList = messageListRef.current

    messageList?.scrollTo({ top: messageList.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const hasConversation = useMemo(() => messages.some(message => message.role === 'user'), [messages])

  const updateAssistant = (id: string, update: (message: ChatMessage) => ChatMessage) => {
    setMessages(current => current.map(message => (message.id === id ? update(message) : message)))
  }

  const sendMessage = async (requestedMessage?: string) => {
    const message = (requestedMessage ?? input).trim()

    if (!message || isStreaming || !sessionId) return

    const userMessage: ChatMessage = { id: createId(), role: 'user', content: message }
    const assistantId = createId()
    const assistantMessage: ChatMessage = { id: assistantId, role: 'assistant', content: '', pending: true }
    const controller = new AbortController()

    setMessages(current => [...current, userMessage, assistantMessage])
    setInput('')
    setIsStreaming(true)
    abortRef.current = controller

    try {
      const response = await fetch(withBasePath('/api/backend/chat'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, session_id: sessionId, role }),
        signal: controller.signal
      })

      if (!response.ok) {
        const error = (await response.json().catch(() => null)) as { message?: string } | null

        throw new Error(error?.message || `请求失败（HTTP ${response.status}）`)
      }

      await consumeSse(response, (event, data) => {
        const payload = data as Record<string, unknown>

        if (event === 'meta' && typeof payload.session_id === 'string') {
          setSessionId(payload.session_id)
          window.localStorage.setItem('grain-learning-session', payload.session_id)
        }

        if (event === 'delta' && typeof payload.content === 'string') {
          updateAssistant(assistantId, current => ({
            ...current,
            content: current.content + payload.content,
            pending: true
          }))
        }

        if (event === 'citations' && Array.isArray(payload.items)) {
          updateAssistant(assistantId, current => ({ ...current, citations: payload.items as Citation[] }))
        }

        if (event === 'error') {
          const messageText = typeof payload.message === 'string' ? payload.message : '生成回答时发生错误。'

          updateAssistant(assistantId, current => ({ ...current, content: messageText, error: true, pending: false }))
        }

        if (event === 'done') {
          updateAssistant(assistantId, current => ({ ...current, pending: false }))
        }
      })
    } catch (error) {
      const stopped = error instanceof DOMException && error.name === 'AbortError'

      updateAssistant(assistantId, current => ({
        ...current,
        content: current.content || (stopped ? '已停止本次生成。' : error instanceof Error ? error.message : '请求失败。'),
        error: !stopped,
        pending: false
      }))
    } finally {
      abortRef.current = null
      setIsStreaming(false)
    }
  }

  const clearConversation = () => {
    abortRef.current?.abort()
    const nextSession = createId()

    window.localStorage.setItem('grain-learning-session', nextSession)
    setSessionId(nextSession)
    setMessages([welcomeMessage])
    setInput('')
  }

  return (
    <Grid container spacing={6}>
      <Grid item xs={12} lg={4} xl={3}>
        <Stack spacing={4}>
          <Card>
            <CardContent>
              <div className='mb-4 flex items-start justify-between gap-3'>
                <div>
                  <Typography variant='h5' className='font-semibold'>学习任务</Typography>
                  <Typography variant='body2' color='text.secondary'>从一个明确目标开始</Typography>
                </div>
                <Avatar variant='rounded' sx={{ bgcolor: 'primary.lighterOpacity', color: 'primary.main' }}>
                  <i className='ri-graduation-cap-line' />
                </Avatar>
              </div>
              <Stack spacing={2}>
                {quickPrompts.map(item => (
                  <Button
                    key={item.title}
                    variant='outlined'
                    color='inherit'
                    disabled={isStreaming || !sessionId}
                    onClick={() => void sendMessage(item.prompt)}
                    sx={{ justifyContent: 'flex-start', textAlign: 'left', p: 3, borderColor: 'divider' }}
                  >
                    <i className={`${item.icon} me-3 text-xl text-primary`} />
                    <span>
                      <span className='block font-medium text-textPrimary'>{item.title}</span>
                      <span className='block text-xs font-normal text-textSecondary'>{item.description}</span>
                    </span>
                  </Button>
                ))}
              </Stack>
            </CardContent>
          </Card>

          <Alert severity='info' icon={<i className='ri-shield-check-line' />}>
            回答会经过课程资料检索与引用校验。提交问题时，相关资料片段将发送给讯飞 MaaS 生成回答。
          </Alert>
        </Stack>
      </Grid>

      <Grid item xs={12} lg={8} xl={9}>
        <Card sx={{ height: { xs: 'auto', lg: 'calc(100vh - 150px)' }, minHeight: 680, display: 'flex', flexDirection: 'column' }}>
          <CardContent className='flex items-center justify-between gap-4' sx={{ py: 3 }}>
            <div className='flex items-center gap-3'>
              <Avatar sx={{ bgcolor: 'primary.main' }}><i className='ri-sparkling-2-line' /></Avatar>
              <div>
                <Typography variant='h5' className='font-semibold'>粮储智能问答</Typography>
                <div className='flex items-center gap-2'>
                  <span className='size-2 rounded-full bg-success' />
                  <Typography variant='caption' color='text.secondary'>检索课程资料后回答</Typography>
                </div>
              </div>
            </div>
            <div className='flex items-center gap-2'>
              <FormControl size='small' sx={{ minWidth: 120 }}>
                <InputLabel id='role-label'>回答角色</InputLabel>
                <Select
                  labelId='role-label'
                  value={role}
                  label='回答角色'
                  onChange={event => setRole(event.target.value as UserRole)}
                  disabled={isStreaming}
                >
                  {Object.entries(roleLabels).map(([value, label]) => (
                    <MenuItem key={value} value={value}>{label}</MenuItem>
                  ))}
                </Select>
              </FormControl>
              <IconButton aria-label='新建会话' title='新建会话' onClick={clearConversation}>
                <i className='ri-chat-new-line' />
              </IconButton>
            </div>
          </CardContent>
          <Divider />

          <Box
            ref={messageListRef}
            sx={{ flex: 1, overflowY: 'auto', p: { xs: 4, md: 6 }, bgcolor: 'customColors.chatBg' }}
          >
            <Stack spacing={5}>
              {messages.map(message => (
                <Box
                  key={message.id}
                  sx={{ display: 'flex', justifyContent: message.role === 'user' ? 'flex-end' : 'flex-start', gap: 2 }}
                >
                  {message.role === 'assistant' && (
                    <Avatar sx={{ width: 34, height: 34, bgcolor: 'primary.main' }}>
                      <i className='ri-seedling-line text-lg' />
                    </Avatar>
                  )}
                  <Box sx={{ maxWidth: { xs: '88%', md: '78%' } }}>
                    <Box
                      sx={{
                        px: 4,
                        py: 3,
                        borderRadius: 3,
                        whiteSpace: 'pre-wrap',
                        overflowWrap: 'anywhere',
                        color: message.role === 'user' ? 'primary.contrastText' : message.error ? 'error.main' : 'text.primary',
                        bgcolor: message.role === 'user' ? 'primary.main' : 'background.paper',
                        boxShadow: message.role === 'assistant' ? 1 : 0
                      }}
                    >
                      {message.content || (message.pending && <span className='flex items-center gap-2'><CircularProgress size={16} />正在检索课程资料并生成回答…</span>)}
                    </Box>
                    {!!message.citations?.length && (
                      <Box sx={{ mt: 2 }}>
                        <Typography variant='caption' color='text.secondary' sx={{ ml: 1 }}>
                          本次回答引用 {message.citations.length} 条证据
                        </Typography>
                        {message.citations.map((citation, index) => (
                          <Accordion key={citation.evidence_id} disableGutters elevation={0} sx={{ mt: 1, border: 1, borderColor: 'divider', borderRadius: '8px !important', '&:before': { display: 'none' } }}>
                            <AccordionSummary expandIcon={<i className='ri-arrow-down-s-line' />}>
                              <div className='flex min-w-0 items-center gap-2'>
                                <Chip label={`E${index + 1}`} size='small' color='primary' />
                                <Typography variant='body2' className='truncate font-medium'>
                                  {citation.title || citation.source || '课程资料'}
                                </Typography>
                              </div>
                            </AccordionSummary>
                            <AccordionDetails>
                              <Typography variant='caption' color='text.secondary' className='block break-all'>
                                {citation.source}{citation.page != null ? ` · 第 ${citation.page} 页` : ''}
                                {citation.score != null ? ` · 相似度 ${(citation.score * 100).toFixed(1)}%` : ''}
                              </Typography>
                              {citation.text && (
                                <Typography variant='body2' sx={{ mt: 2, whiteSpace: 'pre-wrap' }}>{citation.text}</Typography>
                              )}
                            </AccordionDetails>
                          </Accordion>
                        ))}
                      </Box>
                    )}
                  </Box>
                </Box>
              ))}
            </Stack>
          </Box>

          <Divider />
          <Box sx={{ p: { xs: 3, md: 4 } }}>
            <div className='flex items-end gap-3'>
              <TextField
                fullWidth
                multiline
                minRows={1}
                maxRows={5}
                value={input}
                placeholder='输入粮食储藏课程问题，Shift + Enter 换行…'
                onChange={event => setInput(event.target.value)}
                onKeyDown={event => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault()
                    void sendMessage()
                  }
                }}
                disabled={isStreaming}
              />
              {isStreaming ? (
                <Button variant='outlined' color='error' onClick={() => abortRef.current?.abort()} sx={{ minWidth: 92, height: 56 }}>
                  停止
                </Button>
              ) : (
                <Button
                  variant='contained'
                  disabled={!input.trim() || !sessionId}
                  onClick={() => void sendMessage()}
                  endIcon={<i className='ri-send-plane-2-line' />}
                  sx={{ minWidth: 92, height: 56 }}
                >
                  发送
                </Button>
              )}
            </div>
            {!hasConversation && (
              <Typography variant='caption' color='text.secondary' sx={{ display: 'block', mt: 2 }}>
                示例：低温储粮为什么能抑制害虫？
              </Typography>
            )}
          </Box>
        </Card>
      </Grid>
    </Grid>
  )
}

export default ChatWorkspace

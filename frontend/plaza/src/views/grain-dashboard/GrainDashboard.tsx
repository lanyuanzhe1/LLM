'use client'

import { useEffect, useState } from 'react'

import Link from 'next/link'

import Alert from '@mui/material/Alert'
import Avatar from '@mui/material/Avatar'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import Grid from '@mui/material/Grid'
import LinearProgress from '@mui/material/LinearProgress'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'

import { withBasePath } from '@/lib/base-path'

type BackendStatus = {
  status: string
  vectors?: number
  dimension?: number
}

type KnowledgeStatus = {
  documentCount?: number
  chunkCount?: number
}

const tasks = [
  {
    title: '概念讲解',
    description: '理解关键概念、作用机制与适用条件',
    icon: 'ri-lightbulb-flash-line',
    color: '#8C57FF',
    prompt: '请结合课程资料讲解低温储粮的核心概念、作用机制、适用条件和易错点。'
  },
  {
    title: '课程总结',
    description: '从资料中提炼知识点和复习提纲',
    icon: 'ri-file-list-3-line',
    color: '#C1842B',
    prompt: '请基于课程资料总结低温储粮的关键知识点，并给出复习提纲。'
  },
  {
    title: '生成练习',
    description: '由易到难逐题练习并获得反馈',
    icon: 'ri-question-answer-line',
    color: '#4E6BA6',
    prompt: '请基于课程资料生成3道由易到难的练习题，先只展示第1道且不要公布答案。'
  },
  {
    title: '学习规划',
    description: '结合基础和时间制定复习计划',
    icon: 'ri-calendar-schedule-line',
    color: '#9C5B73',
    prompt: '我想在7天内复习粮食储藏课程，请先询问我的基础和每天可用时间。'
  }
]

const GrainDashboard = () => {
  const [backend, setBackend] = useState<BackendStatus | null>(null)
  const [knowledge, setKnowledge] = useState<KnowledgeStatus | null>(null)
  const [loadFailed, setLoadFailed] = useState(false)

  useEffect(() => {
    Promise.all([
      fetch(withBasePath('/api/backend/health'), { cache: 'no-store' }).then(async response => {
        if (!response.ok) throw new Error('backend unavailable')

        return response.json() as Promise<BackendStatus>
      }),
      fetch(withBasePath('/api/knowledge'), { cache: 'no-store' }).then(async response => {
        if (!response.ok) throw new Error('knowledge unavailable')

        return response.json() as Promise<KnowledgeStatus>
      })
    ])
      .then(([backendData, knowledgeData]) => {
        setBackend(backendData)
        setKnowledge(knowledgeData)
      })
      .catch(() => setLoadFailed(true))
  }, [])

  const isReady = backend?.status === 'ready'

  return (
    <Grid container spacing={6}>
      <Grid item xs={12}>
        <Card
          sx={{
            overflow: 'hidden',
            color: 'common.white',
            background: 'linear-gradient(125deg, #6F42C1 0%, #8C57FF 52%, #A379FF 100%)'
          }}
        >
          <CardContent sx={{ position: 'relative', p: { xs: 6, md: 8 }, '&:last-child': { pb: { xs: 6, md: 8 } } }}>
            <Box
              sx={{
                position: 'absolute',
                insetInlineEnd: -80,
                insetBlockStart: -100,
                width: 330,
                height: 330,
                borderRadius: '50%',
                bgcolor: 'rgba(255,255,255,.08)'
              }}
            />
            <Box sx={{ position: 'relative', maxWidth: 720 }}>
              <Chip
                label='粮食储藏课程 RAG 助手'
                size='small'
                sx={{ mb: 4, color: 'white', bgcolor: 'rgba(255,255,255,.16)' }}
              />
              <Typography variant='h3' sx={{ color: 'inherit', mb: 3, fontWeight: 700 }}>
                从课程资料出发，把每个问题学明白
              </Typography>
              <Typography sx={{ color: 'rgba(255,255,255,.82)', mb: 5, maxWidth: 620, fontSize: '1.05rem' }}>
                基于论文、标准与教材进行语义检索，生成带证据引用的回答，并支持总结、练习和储粮案例分析。
              </Typography>
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={3}>
                <Button
                  component={Link}
                  href='/chat'
                  variant='contained'
                  size='large'
                  startIcon={<i className='ri-sparkling-2-line' />}
                  sx={{ bgcolor: 'white', color: '#7E4EE6', '&:hover': { bgcolor: '#F6F1FF' } }}
                >
                  开始智能问答
                </Button>
                <Button
                  component={Link}
                  href='/knowledge'
                  variant='outlined'
                  size='large'
                  startIcon={<i className='ri-book-open-line' />}
                  sx={{ color: 'white', borderColor: 'rgba(255,255,255,.55)', '&:hover': { borderColor: 'white' } }}
                >
                  查看课程资料
                </Button>
              </Stack>
            </Box>
          </CardContent>
        </Card>
      </Grid>

      {[
        { label: '课程资料', value: knowledge?.documentCount ?? '—', suffix: '份', icon: 'ri-folder-open-line', color: 'primary' },
        { label: '知识片段', value: backend?.vectors ?? knowledge?.chunkCount ?? '—', suffix: '条', icon: 'ri-node-tree', color: 'info' },
        { label: '向量维度', value: backend?.dimension ?? '—', suffix: '维', icon: 'ri-bubble-chart-line', color: 'warning' },
        { label: '学习任务', value: 6, suffix: '类', icon: 'ri-graduation-cap-line', color: 'secondary' }
      ].map(stat => (
        <Grid item xs={12} sm={6} lg={3} key={stat.label}>
          <Card>
            <CardContent className='flex items-center gap-4'>
              <Avatar variant='rounded' color={stat.color as 'primary'} sx={{ width: 48, height: 48 }}>
                <i className={`${stat.icon} text-2xl`} />
              </Avatar>
              <div>
                <Typography color='text.secondary' variant='body2'>{stat.label}</Typography>
                <Typography variant='h5' className='font-semibold'>
                  {stat.value}<Typography component='span' color='text.secondary' sx={{ ml: 1 }}>{stat.suffix}</Typography>
                </Typography>
              </div>
            </CardContent>
          </Card>
        </Grid>
      ))}

      <Grid item xs={12} lg={8}>
        <Card>
          <CardContent>
            <div className='mb-5 flex items-center justify-between gap-4'>
              <div>
                <Typography variant='h5' className='font-semibold'>学习任务</Typography>
                <Typography color='text.secondary'>选择一种方式开始本轮学习</Typography>
              </div>
              <Button component={Link} href='/chat' endIcon={<i className='ri-arrow-right-line' />}>自由提问</Button>
            </div>
            <Grid container spacing={4}>
              {tasks.map(task => (
                <Grid item xs={12} sm={6} key={task.title}>
                  <Card
                    component={Link}
                    href={`/chat?prompt=${encodeURIComponent(task.prompt)}`}
                    variant='outlined'
                    sx={{ display: 'block', height: '100%', transition: 'all .2s ease', '&:hover': { borderColor: task.color, transform: 'translateY(-2px)', boxShadow: 3 } }}
                  >
                    <CardContent className='flex gap-4'>
                      <Avatar variant='rounded' sx={{ bgcolor: `${task.color}18`, color: task.color }}>
                        <i className={task.icon} />
                      </Avatar>
                      <div>
                        <Typography variant='h6' className='font-semibold'>{task.title}</Typography>
                        <Typography variant='body2' color='text.secondary'>{task.description}</Typography>
                      </div>
                    </CardContent>
                  </Card>
                </Grid>
              ))}
            </Grid>
          </CardContent>
        </Card>
      </Grid>

      <Grid item xs={12} lg={4}>
        <Card sx={{ height: '100%' }}>
          <CardContent>
            <div className='mb-5 flex items-center justify-between'>
              <Typography variant='h5' className='font-semibold'>系统状态</Typography>
              <Chip
                label={isReady ? '服务就绪' : loadFailed ? '连接异常' : '正在检查'}
                color={isReady ? 'success' : loadFailed ? 'error' : 'default'}
                size='small'
              />
            </div>
            {!backend && !loadFailed && <LinearProgress sx={{ mb: 4 }} />}
            {loadFailed && (
              <Alert severity='warning' sx={{ mb: 4 }}>
                无法连接后端。请先启动 FastAPI 服务。
              </Alert>
            )}
            <Stack spacing={4}>
              <div className='flex items-center justify-between'>
                <Typography color='text.secondary'>知识检索</Typography>
                <Typography className='font-medium'>{isReady ? '正常' : '等待连接'}</Typography>
              </div>
              <div className='flex items-center justify-between'>
                <Typography color='text.secondary'>Embedding</Typography>
                <Typography className='font-medium'>讯飞 · 2560维</Typography>
              </div>
              <div className='flex items-center justify-between'>
                <Typography color='text.secondary'>回答生成</Typography>
                <Typography className='font-medium'>讯飞 MaaS</Typography>
              </div>
              <div className='flex items-center justify-between'>
                <Typography color='text.secondary'>引用校验</Typography>
                <Typography className='font-medium'>已启用</Typography>
              </div>
            </Stack>
          </CardContent>
        </Card>
      </Grid>
    </Grid>
  )
}

export default GrainDashboard

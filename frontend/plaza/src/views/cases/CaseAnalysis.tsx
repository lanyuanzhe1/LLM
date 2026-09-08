'use client'

import { useEffect, useState } from 'react'

import Accordion from '@mui/material/Accordion'
import AccordionDetails from '@mui/material/AccordionDetails'
import AccordionSummary from '@mui/material/AccordionSummary'
import Alert from '@mui/material/Alert'
import Avatar from '@mui/material/Avatar'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import Grid from '@mui/material/Grid'
import MenuItem from '@mui/material/MenuItem'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'

import { consumeSse } from '@/lib/consumeSse'
import { withBasePath } from '@/lib/base-path'
import { genId } from '@/utils/genId'
import type { Citation } from '@/types/grain'

type FormState = {
  grain_type: string
  storage_type: string
  storage_days: string
  moisture_percent: string
  grain_temperature_c: string
  temperature_trend: string
  ambient_temperature_c: string
  ambient_humidity_percent: string
  co2_ppm: string
  co2_trend: string
  pest_signs: string
  mold_signs: string
  condensation_signs: string
  goal: string
}

const emptyForm: FormState = {
  grain_type: '',
  storage_type: '',
  storage_days: '',
  moisture_percent: '',
  grain_temperature_c: '',
  temperature_trend: '',
  ambient_temperature_c: '',
  ambient_humidity_percent: '',
  co2_ppm: '',
  co2_trend: '',
  pest_signs: '',
  mold_signs: '',
  condensation_signs: '',
  goal: ''
}

const sampleForm: FormState = {
  grain_type: '小麦',
  storage_type: '高大平房仓，常规储藏',
  storage_days: '120',
  moisture_percent: '13.2',
  grain_temperature_c: '24',
  temperature_trend: 'rising',
  ambient_temperature_c: '29',
  ambient_humidity_percent: '76',
  co2_ppm: '850',
  co2_trend: 'rising',
  pest_signs: 'false',
  mold_signs: 'false',
  condensation_signs: 'true',
  goal: '分析当前粮堆的霉变和粮温风险，并给出需要优先核查的信息。'
}

const optionalNumberFields = [
  'storage_days',
  'moisture_percent',
  'grain_temperature_c',
  'ambient_temperature_c',
  'ambient_humidity_percent',
  'co2_ppm'
] as const

const CaseAnalysis = () => {
  const [form, setForm] = useState<FormState>(emptyForm)
  const [sessionId, setSessionId] = useState('')
  const [result, setResult] = useState('')
  const [citations, setCitations] = useState<Citation[]>([])
  const [missingFields, setMissingFields] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const stored = window.localStorage.getItem('grain-case-session') || genId()

    window.localStorage.setItem('grain-case-session', stored)
    setSessionId(stored)
  }, [])

  const update = (field: keyof FormState, value: string) => setForm(current => ({ ...current, [field]: value }))

  const buildCase = () => {
    const payload: Record<string, string | number | boolean> = {}

    for (const field of ['grain_type', 'storage_type', 'temperature_trend', 'co2_trend', 'goal'] as const) {
      if (form[field].trim()) payload[field] = form[field].trim()
    }

    for (const field of optionalNumberFields) {
      if (form[field] !== '') payload[field] = Number(form[field])
    }

    for (const field of ['pest_signs', 'mold_signs', 'condensation_signs'] as const) {
      if (form[field] !== '') payload[field] = form[field] === 'true'
    }

    return payload
  }

  const analyze = async () => {
    if (!form.goal.trim() || !sessionId || loading) return

    setLoading(true)
    setResult('')
    setCitations([])
    setMissingFields([])
    setError('')

    try {
      const response = await fetch(withBasePath('/api/backend/cases'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, role: 'technician', case: buildCase() })
      })

      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as { message?: string } | null

        throw new Error(payload?.message || `分析失败（HTTP ${response.status}）`)
      }

      await consumeSse(response, (event, data) => {
        const payload = data as Record<string, unknown>

        if (event === 'meta' && typeof payload.session_id === 'string') {
          window.localStorage.setItem('grain-case-session', payload.session_id)
          setSessionId(payload.session_id)
        }

        if (event === 'delta' && typeof payload.content === 'string') setResult(current => current + payload.content)
        if (event === 'citations' && Array.isArray(payload.items)) setCitations(payload.items as Citation[])
        if (event === 'done' && Array.isArray(payload.missing_fields)) setMissingFields(payload.missing_fields as string[])
        if (event === 'error') throw new Error(typeof payload.message === 'string' ? payload.message : '案例分析失败。')
      })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '案例分析失败。')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Grid container spacing={6}>
      <Grid item xs={12}>
        <Card>
          <CardContent className='flex flex-col justify-between gap-4 md:flex-row md:items-center'>
            <div className='flex items-center gap-4'>
              <Avatar variant='rounded' sx={{ width: 56, height: 56, bgcolor: 'warning.lighterOpacity', color: 'warning.main' }}>
                <i className='ri-pulse-line text-3xl' />
              </Avatar>
              <div>
                <Typography variant='h4' className='font-semibold'>储粮案例分析</Typography>
                <Typography color='text.secondary'>填写现场指标，系统会先检查信息完整性，再结合课程证据分析</Typography>
              </div>
            </div>
            <Button variant='outlined' startIcon={<i className='ri-flask-line' />} onClick={() => setForm(sampleForm)}>
              填入示例
            </Button>
          </CardContent>
        </Card>
      </Grid>

      <Grid item xs={12} lg={7}>
        <Card>
          <CardContent>
            <Typography variant='h5' className='mb-1 font-semibold'>案例信息</Typography>
            <Typography variant='body2' color='text.secondary' className='mb-5'>不知道的指标可以留空，系统会指出影响本次目标的缺失项。</Typography>
            <Grid container spacing={4}>
              <Grid item xs={12} sm={6}>
                <TextField fullWidth label='粮食品种' value={form.grain_type} onChange={event => update('grain_type', event.target.value)} placeholder='例如：小麦' />
              </Grid>
              <Grid item xs={12} sm={6}>
                <TextField fullWidth label='仓型与储藏方式' value={form.storage_type} onChange={event => update('storage_type', event.target.value)} placeholder='例如：高大平房仓' />
              </Grid>
              <Grid item xs={12} sm={4}>
                <TextField fullWidth type='number' label='储藏天数' value={form.storage_days} onChange={event => update('storage_days', event.target.value)} />
              </Grid>
              <Grid item xs={12} sm={4}>
                <TextField fullWidth type='number' label='粮食水分（%）' value={form.moisture_percent} onChange={event => update('moisture_percent', event.target.value)} />
              </Grid>
              <Grid item xs={12} sm={4}>
                <TextField fullWidth type='number' label='粮温（℃）' value={form.grain_temperature_c} onChange={event => update('grain_temperature_c', event.target.value)} />
              </Grid>
              <Grid item xs={12} sm={4}>
                <TextField select fullWidth label='粮温趋势' value={form.temperature_trend} onChange={event => update('temperature_trend', event.target.value)}>
                  <MenuItem value=''>未知</MenuItem><MenuItem value='rising'>上升</MenuItem><MenuItem value='stable'>稳定</MenuItem><MenuItem value='falling'>下降</MenuItem>
                </TextField>
              </Grid>
              <Grid item xs={12} sm={4}>
                <TextField fullWidth type='number' label='环境温度（℃）' value={form.ambient_temperature_c} onChange={event => update('ambient_temperature_c', event.target.value)} />
              </Grid>
              <Grid item xs={12} sm={4}>
                <TextField fullWidth type='number' label='环境湿度（%）' value={form.ambient_humidity_percent} onChange={event => update('ambient_humidity_percent', event.target.value)} />
              </Grid>
              <Grid item xs={12} sm={6}>
                <TextField fullWidth type='number' label='CO₂ 浓度（ppm）' value={form.co2_ppm} onChange={event => update('co2_ppm', event.target.value)} />
              </Grid>
              <Grid item xs={12} sm={6}>
                <TextField select fullWidth label='CO₂ 趋势' value={form.co2_trend} onChange={event => update('co2_trend', event.target.value)}>
                  <MenuItem value=''>未知</MenuItem><MenuItem value='rising'>上升</MenuItem><MenuItem value='stable'>稳定</MenuItem><MenuItem value='falling'>下降</MenuItem>
                </TextField>
              </Grid>
              {[
                ['pest_signs', '发现虫害迹象'],
                ['mold_signs', '发现霉变迹象'],
                ['condensation_signs', '发现结露迹象']
              ].map(([field, label]) => (
                <Grid item xs={12} sm={4} key={field}>
                  <TextField select fullWidth label={label} value={form[field as keyof FormState]} onChange={event => update(field as keyof FormState, event.target.value)}>
                    <MenuItem value=''>未知</MenuItem><MenuItem value='true'>是</MenuItem><MenuItem value='false'>否</MenuItem>
                  </TextField>
                </Grid>
              ))}
              <Grid item xs={12}>
                <TextField
                  fullWidth multiline minRows={3} required label='分析目标'
                  value={form.goal} onChange={event => update('goal', event.target.value)}
                  placeholder='例如：分析霉变风险、粮温异常或虫害风险，并说明下一步应该核查什么。'
                />
              </Grid>
              <Grid item xs={12}>
                <div className='flex flex-wrap justify-end gap-3'>
                  <Button variant='text' color='inherit' disabled={loading} onClick={() => setForm(emptyForm)}>清空</Button>
                  <Button variant='contained' disabled={loading || !form.goal.trim() || !sessionId} onClick={() => void analyze()} startIcon={loading ? <CircularProgress size={18} color='inherit' /> : <i className='ri-search-eye-line' />}>
                    {loading ? '正在分析' : '开始分析'}
                  </Button>
                </div>
              </Grid>
            </Grid>
          </CardContent>
        </Card>
      </Grid>

      <Grid item xs={12} lg={5}>
        <Stack spacing={4}>
          <Card sx={{ minHeight: 420 }}>
            <CardContent>
              <div className='mb-4 flex items-center justify-between gap-3'>
                <Typography variant='h5' className='font-semibold'>分析结果</Typography>
                {result && <Chip label={missingFields.length ? '需要补充信息' : '分析完成'} size='small' color={missingFields.length ? 'warning' : 'success'} />}
              </div>
              {error && <Alert severity='error' sx={{ mb: 4 }}>{error}</Alert>}
              {!result && !loading && !error && (
                <div className='flex min-h-[300px] flex-col items-center justify-center text-center'>
                  <Avatar sx={{ width: 64, height: 64, mb: 4, bgcolor: 'action.hover', color: 'text.secondary' }}>
                    <i className='ri-file-search-line text-3xl' />
                  </Avatar>
                  <Typography className='font-medium'>等待案例信息</Typography>
                  <Typography variant='body2' color='text.secondary' sx={{ maxWidth: 300 }}>
                    系统不会在关键指标缺失时直接给出未经支持的结论。
                  </Typography>
                </div>
              )}
              {loading && !result && (
                <div className='flex min-h-[300px] flex-col items-center justify-center gap-3'>
                  <CircularProgress />
                  <Typography color='text.secondary'>正在检查指标并核对课程资料…</Typography>
                </div>
              )}
              {result && <Typography sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.9 }}>{result}</Typography>}
              {!!missingFields.length && (
                <Alert severity='warning' sx={{ mt: 4 }}>缺失字段：{missingFields.join('、')}</Alert>
              )}
            </CardContent>
          </Card>

          {!!citations.length && (
            <Card>
              <CardContent>
                <Typography variant='h6' className='mb-3 font-semibold'>参考证据</Typography>
                {citations.map((citation, index) => (
                  <Accordion key={citation.evidence_id} disableGutters elevation={0} sx={{ borderTop: 1, borderColor: 'divider', '&:before': { display: 'none' } }}>
                    <AccordionSummary expandIcon={<i className='ri-arrow-down-s-line' />}>
                      <div className='flex min-w-0 items-center gap-2'>
                        <Chip label={`E${index + 1}`} size='small' color='primary' />
                        <Typography variant='body2' className='truncate'>{citation.title || citation.source}</Typography>
                      </div>
                    </AccordionSummary>
                    <AccordionDetails>
                      <Typography variant='caption' color='text.secondary'>{citation.source}</Typography>
                      {citation.text && <Typography variant='body2' sx={{ mt: 2 }}>{citation.text}</Typography>}
                    </AccordionDetails>
                  </Accordion>
                ))}
              </CardContent>
            </Card>
          )}
        </Stack>
      </Grid>
    </Grid>
  )
}

export default CaseAnalysis
